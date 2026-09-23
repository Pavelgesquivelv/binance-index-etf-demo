from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.accounting.execution_accounting import (
    ExecutionAccounting,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.execution.reconciler import (
    OrderReconciler,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.storage.database import (
    Database,
)


TEST_META_KEY = (
    "single_bnb_execution_test_completed"
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def load_config() -> dict:
    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:
        return yaml.safe_load(file)


def get_free_balance(
    account: dict,
    asset: str,
) -> Decimal:

    for balance in account.get(
        "balances",
        [],
    ):
        if balance["asset"] == asset:
            return Decimal(
                balance["free"]
            )

    return Decimal("0")


def get_recoverable(
    database: Database,
    repository: OrderRepository,
) -> list[dict]:

    with database.connection() as conn:
        return (
            repository
            .get_recoverable_orders(
                conn
            )
        )


def get_local_order(
    database: Database,
    repository: OrderRepository,
    client_order_id: str,
) -> dict:

    rows = get_recoverable(
        database,
        repository,
    )

    matches = [
        row
        for row in rows
        if row["client_order_id"]
        == client_order_id
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Expected exactly one "
            "recoverable local order for "
            f"{client_order_id}; "
            f"found {len(matches)}."
        )

    return matches[0]


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute-single-bnb",
        action="store_true",
        help=(
            "Actually send exactly one "
            "BNBUSDC MARKET BUY to Binance Demo."
        ),
    )

    args = parser.parse_args()

    config = load_config()

    base_currency = (
        config["fund"]["base_currency"]
        .upper()
    )

    test_asset = (
        config["execution"][
            "single_order_test_asset"
        ]
        .upper()
    )

    test_notional = Decimal(
        str(
            config["execution"][
                "single_order_test_usdc"
            ]
        )
    )

    if test_asset != "BNB":
        raise RuntimeError(
            "This controlled test only "
            "supports BNB."
        )

    if (
        test_notional < Decimal("5")
        or test_notional > Decimal("25")
    ):
        raise RuntimeError(
            "Single-order test notional "
            "must be between 5 and 25 USDC."
        )

    # -------------------------------------------------
    # ETF database
    # -------------------------------------------------

    database = Database(
        str(
            ROOT
            / config["storage"][
                "database"
            ]
        )
    )

    ledger = PortfolioLedger(
        database
    )

    repository = (
        OrderRepository()
    )

    accounting = (
        ExecutionAccounting(
            base_currency=base_currency
        )
    )

    # -------------------------------------------------
    # Never repeat this one-time test accidentally.
    # -------------------------------------------------

    with database.connection() as conn:

        completed = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key = ?
            """,
            (TEST_META_KEY,),
        ).fetchone()

    if completed is not None:
        raise RuntimeError(
            "Single BNB execution test "
            "was already completed.\n"
            f"Recorded value: "
            f"{completed['value']}"
        )

    # -------------------------------------------------
    # No unresolved ETF orders may exist.
    # -------------------------------------------------

    recoverable = get_recoverable(
        database,
        repository,
    )

    if recoverable:
        print(
            "Execution blocked: unresolved "
            "ETF orders exist."
        )

        for row in recoverable:
            print(
                f"  "
                f"{row['client_order_id']} "
                f"{row['local_status']}"
            )

        raise RuntimeError(
            "Resolve existing orders first."
        )

    # -------------------------------------------------
    # ETF ledger cash
    # -------------------------------------------------

    ledger_cash = (
        ledger.get_cash_balance(
            base_currency
        )
    )

    if ledger_cash < test_notional:
        raise RuntimeError(
            "ETF ledger has insufficient "
            f"{base_currency}."
        )

    # -------------------------------------------------
    # Binance client
    # -------------------------------------------------

    client = BinanceDemoClient()

    print("=" * 80)
    print(
        "SINGLE BNB DEMO EXECUTION CHECK"
    )
    print("=" * 80)

    print()
    print(
        f"Base URL          : "
        f"{client.base_url}"
    )

    print(
        f"Trading enabled   : "
        f"{client.trading_enabled}"
    )

    print(
        f"ETF ledger cash   : "
        f"{ledger_cash} "
        f"{base_currency}"
    )

    print(
        f"Test order        : "
        f"BUY {test_notional} "
        f"{base_currency} of BNB"
    )

    # -------------------------------------------------
    # Confirm account has enough actual free USDC.
    # -------------------------------------------------

    account = client.get_account()

    exchange_free_usdc = (
        get_free_balance(
            account,
            base_currency,
        )
    )

    print(
        f"Binance free USDC : "
        f"{exchange_free_usdc}"
    )

    if exchange_free_usdc < test_notional:
        raise RuntimeError(
            "Binance Demo account has "
            "insufficient free USDC."
        )

    # -------------------------------------------------
    # Validate BNBUSDC market.
    # -------------------------------------------------

    symbol = (
        f"{test_asset}"
        f"{base_currency}"
    )

    exchange_info = (
        client.get_exchange_info()
    )

    symbol_info = next(
        (
            item
            for item
            in exchange_info["symbols"]
            if item["symbol"] == symbol
        ),
        None,
    )

    if symbol_info is None:
        raise RuntimeError(
            f"{symbol} does not exist."
        )

    if (
        symbol_info["status"]
        != "TRADING"
    ):
        raise RuntimeError(
            f"{symbol} is not TRADING."
        )

    if not symbol_info.get(
        "quoteOrderQtyMarketAllowed",
        False,
    ):
        raise RuntimeError(
            f"{symbol} does not allow "
            "MARKET quoteOrderQty."
        )

    # -------------------------------------------------
    # Exact order preflight.
    # Still no execution.
    # -------------------------------------------------

    preflight = (
        client.test_market_order(
            symbol=symbol,
            side="BUY",
            quote_order_qty=str(
                test_notional
            ),
            compute_commission_rates=True,
        )
    )

    print()
    print(
        "Exact order preflight: OK"
    )

    discount = preflight.get(
        "discount",
        {},
    )

    print(
        "BNB fee discount   : "
        f"account="
        f"{discount.get('enabledForAccount')} "
        f"symbol="
        f"{discount.get('enabledForSymbol')}"
    )

    # -------------------------------------------------
    # Dry invocation stops HERE.
    # -------------------------------------------------

    if not args.execute_single_bnb:

        print()
        print(
            "EXECUTION NOT REQUESTED."
        )

        print(
            "No order was sent."
        )

        print()
        print(
            "To perform the controlled "
            "Demo order, both conditions "
            "must be true:"
        )

        print(
            "  BINANCE_TRADING_ENABLED=true"
        )

        print(
            "  --execute-single-bnb"
        )

        return

    # -------------------------------------------------
    # Hard application safety gate.
    # -------------------------------------------------

    client.assert_execution_ready()

    # -------------------------------------------------
    # Load current index metadata for audit trail.
    # -------------------------------------------------

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    # -------------------------------------------------
    # Reserve locally FIRST.
    # This transaction commits before the POST.
    # -------------------------------------------------

    with database.connection() as conn:

        run_id = (
            accounting.start_rebalance(
                conn,
                cutoff_utc=feed.cutoff_utc,
                index_level=feed.index_level,
                nav_before=ledger_cash,
            )
        )

        client_order_id = (
            f"IDXETF_R"
            f"{run_id:06d}"
            f"_01_BNB"
        )

        local_order_id = (
            repository.reserve_order(
                conn,
                rebalance_run_id=run_id,
                client_order_id=(
                    client_order_id
                ),
                symbol=symbol,
                asset=test_asset,
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    test_notional
                ),
            )
        )

    print()
    print(
        f"Local order ID    : "
        f"{local_order_id}"
    )

    print(
        f"clientOrderId     : "
        f"{client_order_id}"
    )

    print(
        "Local status      : RESERVED"
    )

    # -------------------------------------------------
    # Extremely defensive check:
    # this freshly generated ID should not already
    # exist on Binance.
    # -------------------------------------------------

    existing = (
        client.get_order_if_exists(
            symbol=symbol,
            client_order_id=(
                client_order_id
            ),
        )
    )

    # -------------------------------------------------
    # Send only if Binance does not already know it.
    # -------------------------------------------------

    if existing is None:

        print()
        print(
            "Submitting exactly ONE "
            "Demo MARKET order..."
        )

        try:

            response = (
                client.place_market_order(
                    symbol=symbol,
                    side="BUY",
                    client_order_id=(
                        client_order_id
                    ),
                    quote_order_qty=str(
                        test_notional
                    ),
                )
            )

            with database.connection() as conn:

                repository.mark_exchange_ack(
                    conn,
                    order_id=local_order_id,
                    response=response,
                )

            print(
                "Binance order response "
                "received."
            )

        except Exception as exc:

            # Important:
            # unknown submission state.
            # DO NOT retry.
            with database.connection() as conn:

                repository.mark_submit_unknown(
                    conn,
                    order_id=local_order_id,
                    error=str(exc),
                )

            print()
            print(
                "SUBMISSION RESULT UNKNOWN."
            )

            print(
                f"Error: {exc}"
            )

            print(
                "The order will NOT be "
                "submitted again."
            )

    else:

        print()
        print(
            "Binance already knows this "
            "clientOrderId."
        )

        print(
            "No new POST will be sent."
        )

    # -------------------------------------------------
    # Reconcile by clientOrderId / orderId.
    # -------------------------------------------------

    local_order = get_local_order(
        database,
        repository,
        client_order_id,
    )

    reconciler = OrderReconciler(
        database=database,
        client=client,
        base_currency=base_currency,
    )

    result = reconciler.reconcile_order(
        local_order
    )

    print()
    print("=" * 80)
    print("RECONCILIATION RESULT")
    print("=" * 80)

    print(
        f"Result           : "
        f"{result.result}"
    )

    print(
        f"Exchange status  : "
        f"{result.exchange_status}"
    )

    print(
        f"Fills            : "
        f"{result.fills}"
    )

    print(
        f"Message          : "
        f"{result.message}"
    )

    # -------------------------------------------------
    # Only mark the one-time test successful if
    # accounting completed.
    # -------------------------------------------------

    if result.result != "ACCOUNTED":

        print()
        print(
            "Execution requires recovery."
        )

        print(
            "Do NOT rerun this script "
            "to place another order."
        )

        return

    with database.connection() as conn:

        accounting.finish_rebalance(
            conn,
            rebalance_run_id=run_id,
            status=(
                "SINGLE_TEST_COMPLETED"
            ),
            notes=(
                "Controlled BNB Demo "
                "execution test."
            ),
        )

        conn.execute(
            """
            INSERT INTO meta (
                key,
                value
            )
            VALUES (?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
            """,
            (
                TEST_META_KEY,
                (
                    f"{utc_now()}|"
                    f"{client_order_id}"
                ),
            ),
        )

        position = conn.execute(
            """
            SELECT
                quantity,
                average_cost_usdc
            FROM positions
            WHERE asset = 'BNB'
            """
        ).fetchone()

        fee_rows = conn.execute(
            """
            SELECT
                asset,
                amount
            FROM fee_ledger
            WHERE order_id = ?
            ORDER BY id
            """,
            (local_order_id,),
        ).fetchall()

    final_cash = (
        ledger.get_cash_balance(
            base_currency
        )
    )

    print()
    print("=" * 80)
    print("ETF LEDGER AFTER REAL DEMO FILL")
    print("=" * 80)

    print()
    print(
        f"USDC cash        : "
        f"{final_cash}"
    )

    if position:

        print(
            f"BNB ETF position : "
            f"{position['quantity']}"
        )

        print(
            f"BNB avg cost     : "
            f"{position['average_cost_usdc']} "
            f"USDC"
        )

    print()
    print("Actual commissions:")

    for fee in fee_rows:
        print(
            f"  "
            f"{fee['amount']} "
            f"{fee['asset']}"
        )

    print()
    print(
        "SINGLE BNB DEMO TEST: COMPLETE"
    )


if __name__ == "__main__":
    main()
