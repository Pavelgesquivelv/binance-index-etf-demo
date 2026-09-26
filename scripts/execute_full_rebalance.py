from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone
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
from src.exchange.symbol_rules import (
    SymbolRules,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.execution.reconciler import (
    OrderReconciler,
)
from src.index.feed_calendar import (
    CURRENT,
    FUTURE_INVALID,
    STALE_MISSING_MONTHLY_REBALANCE,
    WAITING_FOR_MONTH_END_FEED,
    classify_feed_cutoff,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.portfolio.owned_reserves import (
    build_owned_minimum_reserves_from_database,
)
from src.portfolio.physical_backing import (
    check_physical_backing,
)
from src.rebalance.planner import (
    RebalancePlanner,
)
from src.storage.database import (
    Database,
)

from src.contributions.interlocks import (
    get_blocking_contributions,
)

from src.execution.benchmark_repository import (
    ExecutionBenchmarkRepository,
)

from src.rebalance.funding import (
    make_cash_feasible,
)

ZERO = Decimal("0")


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

    return ZERO


def get_positions(
    ledger: PortfolioLedger,
) -> dict[str, Decimal]:

    return {
        row["asset"]:
            Decimal(row["quantity"])
        for row in ledger.get_positions()
        if Decimal(row["quantity"]) != 0
    }


def require_physical_backing(
    *,
    ledger: PortfolioLedger,
    database: Database,
    account: dict,
    base_currency: str,
    dedicated_bnb_fee_reserve: Decimal,
    context: str,
) -> None:

    cash = ledger.get_cash_balance(
        base_currency
    )

    positions = get_positions(
        ledger
    )

    result = check_physical_backing(
        cash=cash,
        positions=positions,
        account=account,
        base_currency=base_currency,
        minimum_reserves=(
            build_owned_minimum_reserves_from_database(
                database,
                base_currency=base_currency,
                dedicated_bnb_fee_reserve=(
                    dedicated_bnb_fee_reserve
                ),
            )
        ),
    )

    if result.ok:
        return

    details = "; ".join(
        (
            f"{line.asset}: "
            f"ledger={line.ledger_quantity}, "
            f"reserve={line.required_reserve}, "
            f"required={line.required_total}, "
            f"free={line.exchange_free}, "
            f"deficit={-line.surplus}"
        )
        for line in result.deficits
    )

    raise RuntimeError(
        "EXECUTION BLOCKED: physical "
        "backing check failed "
        f"({context}). {details}"
    )


def get_recoverable_orders(
    database: Database,
    repository: OrderRepository,
) -> list[dict]:

    with database.connection() as conn:
        return repository.get_recoverable_orders(
            conn
        )


def get_recoverable_order(
    database: Database,
    repository: OrderRepository,
    client_order_id: str,
) -> dict:

    rows = get_recoverable_orders(
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
            "recoverable order for "
            f"{client_order_id}; "
            f"found {len(matches)}."
        )

    return matches[0]


def calculate_nav(
    *,
    cash: Decimal,
    positions: dict[str, Decimal],
    books: dict[str, dict[str, Decimal]],
    base_currency: str,
) -> tuple[Decimal, Decimal]:

    market_value = ZERO

    for asset, quantity in positions.items():

        symbol = (
            f"{asset}{base_currency}"
        )

        book = books.get(symbol)

        if book is None:
            raise RuntimeError(
                f"No market data for "
                f"ETF position {symbol}."
            )

        mid = (
            book["bid"]
            + book["ask"]
        ) / Decimal("2")

        market_value += (
            quantity * mid
        )

    return (
        cash + market_value,
        market_value,
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute-full-rebalance",
        action="store_true",
        help=(
            "Actually execute the complete "
            "ETF rebalance on Binance Demo."
        ),
    )

    args = parser.parse_args()

    config = load_config()

    base_currency = (
        config["fund"]["base_currency"]
        .upper()
    )

    max_orders = int(
        config["execution"][
            "full_rebalance"
        ]["max_orders"]
    )

    fee_buffer_multiplier = Decimal(
        str(
            config["execution"][
                "full_rebalance"
            ]["fee_buffer_multiplier"]
        )
    )

    dedicated_bnb_fee_reserve = Decimal(
        str(
            config.get(
                "account_isolation",
                {},
            ).get(
                "dedicated_bnb_fee_reserve",
                "0",
            )
        )
    )

    # =====================================================
    # Database / ledger
    # =====================================================

    database = Database(
        str(
            ROOT
            / config["storage"]["database"]
        )
    )

    ledger = PortfolioLedger(
        database
    )

    repository = OrderRepository()

    benchmark_repository = (
        ExecutionBenchmarkRepository()
    )

    accounting = ExecutionAccounting(
        base_currency=base_currency
    )

    # =====================================================
    # Critical safety check:
    # no unresolved previous order.
    # =====================================================

    recoverable = get_recoverable_orders(
        database,
        repository,
    )

    if recoverable:

        print(
            "EXECUTION BLOCKED: "
            "recoverable ETF orders exist."
        )

        for row in recoverable:
            print(
                f"  "
                f"{row['client_order_id']} "
                f"{row['local_status']} "
                f"{row['exchange_status']}"
            )

        raise RuntimeError(
            "Resolve previous ETF orders "
            "before a new rebalance."
        )

    # =====================================================
    # Contribution / rebalance mutual exclusion.
    #
    # Once external capital has been accepted into the
    # ETF, its BUY-only investment must finish before
    # a new index rebalance may start.
    # =====================================================

    with database.connection() as conn:

        blocking_contributions = (
            get_blocking_contributions(
                conn
            )
        )

    if blocking_contributions:

        print(
            "EXECUTION BLOCKED: "
            "contribution investment "
            "is incomplete."
        )

        for row in blocking_contributions:

            print(
                f"  period="
                f"{row['period_id']} "
                f"status="
                f"{row['status']} "
                f"amount="
                f"{row['accepted_amount']}"
            )

        raise RuntimeError(
            "Complete or recover the "
            "contribution investment before "
            "starting a new index rebalance."
        )

    # =====================================================
    # Index portfolio feed
    # =====================================================

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    # =====================================================
    # Duplicate portfolio cutoff safety gate
    #
    # A successfully completed portfolio cutoff
    # must never be rebalanced twice.
    # =====================================================

    with database.connection() as conn:

        previous_completed_run = (
            conn.execute(
                """
                SELECT
                    id,
                    completed_at_utc
                FROM rebalance_runs
                WHERE cutoff_utc = ?
                  AND status = 'COMPLETED'
                ORDER BY id DESC
                LIMIT 1
                """,
                (feed.cutoff_utc,),
            ).fetchone()
        )

    if previous_completed_run is not None:

        raise RuntimeError(
            "EXECUTION BLOCKED: "
            "this portfolio cutoff was "
            "already successfully rebalanced. "
            f"cutoff={feed.cutoff_utc}, "
            f"run_id="
            f"{previous_completed_run['id']}, "
            f"completed_at="
            f"{previous_completed_run['completed_at_utc']}."
        )
    
    # =====================================================
    # Monthly index calendar safety gate.
    #
    # The index reconstitutes/rebalances on the final
    # calendar day of each month at 07:00 CDMX.
    # Portfolio validity therefore depends on the
    # expected monthly cutoff, not an arbitrary age.
    # =====================================================

    calendar_state = (
        classify_feed_cutoff(
            feed.cutoff_utc
        )
    )

    print(
        f"Feed calendar     : "
        f"{calendar_state.status}"
    )

    print(
        f"Expected cutoff   : "
        f"{calendar_state.expected_cutoff_local.isoformat()}"
    )

    print(
        f"Grace deadline    : "
        f"{calendar_state.grace_deadline_local.isoformat()}"
    )

    if (
        calendar_state.status
        == WAITING_FOR_MONTH_END_FEED
    ):
        raise RuntimeError(
            "EXECUTION BLOCKED: month-end "
            "transition window is active. "
            "Waiting for the new monthly "
            "portfolio feed."
        )

    if (
        calendar_state.status
        == STALE_MISSING_MONTHLY_REBALANCE
    ):
        raise RuntimeError(
            "EXECUTION BLOCKED: expected "
            "monthly portfolio feed is missing. "
            "Refusing to execute using stale "
            "index holdings."
        )

    if (
        calendar_state.status
        == FUTURE_INVALID
    ):
        raise RuntimeError(
            "EXECUTION BLOCKED: portfolio "
            "feed cutoff is invalid for the "
            "current monthly index calendar."
        )

    if (
        calendar_state.status
        != CURRENT
    ):
        raise RuntimeError(
            "EXECUTION BLOCKED: unknown "
            "feed calendar state: "
            f"{calendar_state.status}"
        )

    # =====================================================
    # Current ETF state
    # =====================================================

    cash = ledger.get_cash_balance(
        base_currency
    )

    positions = get_positions(
        ledger
    )

    # =====================================================
    # Binance
    # =====================================================

    client = BinanceDemoClient()

    account = client.get_account()

    require_physical_backing(
        ledger=ledger,
        database=database,
        account=account,
        base_currency=base_currency,
        dedicated_bnb_fee_reserve=(
            dedicated_bnb_fee_reserve
        ),
        context="initial preflight",
    )

    print(
        "Physical backing  : OK"
    )

    print(
        "Dedicated BNB reserve: "
        f"{dedicated_bnb_fee_reserve} BNB"
    )

    exchange_info = (
        client.get_exchange_info()
    )

    exchange_symbols = {
        item["symbol"]: item
        for item in exchange_info[
            "symbols"
        ]
    }

    assets = sorted(
        {
            item.asset
            for item in feed.positions
        }
        | set(positions)
    )

    books = {}
    rules = {}

    for asset in assets:

        symbol = (
            f"{asset}{base_currency}"
        )

        info = exchange_symbols.get(
            symbol
        )

        if info is None:
            raise RuntimeError(
                f"Required market "
                f"does not exist: {symbol}"
            )

        if info["status"] != "TRADING":
            raise RuntimeError(
                f"{symbol} is not TRADING."
            )

        rules[symbol] = (
            SymbolRules.from_exchange_info(
                info
            )
        )

        ticker = client.get_book_ticker(
            symbol
        )

        books[symbol] = {
            "bid": Decimal(
                ticker["bidPrice"]
            ),
            "ask": Decimal(
                ticker["askPrice"]
            ),
        }

    # =====================================================
    # Build fresh plan
    # =====================================================

    planner = RebalancePlanner()

    plan = planner.build(
        feed=feed,
        cash=cash,
        positions=positions,
        books=books,
        rules=rules,
        base_currency=base_currency,
    )

    funding = make_cash_feasible(
        plan=plan,
        rules=rules,
    )

    execution_lines = (
        list(funding.sells)
        + list(funding.buys)
    )

    print()
    print(
        f"Projected buying power : "
        f"{funding.buying_power:.8f} "
        f"{base_currency}"
    )

    if funding.skipped_buys:

        print()
        print(
            "UNFUNDED BUY SIGNALS"
        )

        for line in (
            funding.skipped_buys
        ):

            print(
                f"  {line.symbol:12} "
                f"requested="
                f"{line.estimated_notional:.8f} "
                f"{base_currency}"
            )    

    planned_buys = sum(
        (
            line.estimated_notional
            for line in funding.buys
        ),
        ZERO,
    )

    planned_sells = sum(
        (
            line.estimated_notional
            for line in funding.sells
        ),
        ZERO,
    )    

    if not execution_lines:

        print()
        print(
            "No cash-feasible rebalance "
            "orders are required."
        )

        if funding.skipped_buys:

            print()

            print(
                "Underweight assets exist, "
                "but available ETF cash is "
                "below Binance minimum "
                "order requirements."
            )

        print()

        print(
            "No Binance order was sent."
        )

        return

    if len(execution_lines) > max_orders:
        raise RuntimeError(
            f"Plan contains "
            f"{len(execution_lines)} orders; "
            f"configured maximum is "
            f"{max_orders}."
        )

    # =====================================================
    # Preflight every order BEFORE executing any.
    # =====================================================

    preflights = {}

    bnb_discount_detected = False

    for line in execution_lines:

        if line.quote_order_qty is not None:

            response = (
                client.test_market_order(
                    symbol=line.symbol,
                    side=line.action,
                    quote_order_qty=str(
                        line.quote_order_qty
                    ),
                    compute_commission_rates=True,
                )
            )

        else:

            response = (
                client.test_market_order(
                    symbol=line.symbol,
                    side=line.action,
                    quantity=str(
                        line.order_quantity
                    ),
                    compute_commission_rates=True,
                )
            )

        preflights[
            line.symbol
        ] = response

        discount = response.get(
            "discount",
            {},
        )

        if (
            discount.get(
                "enabledForAccount"
            )
            and discount.get(
                "enabledForSymbol"
            )
            and discount.get(
                "discountAsset"
            ) == "BNB"
        ):
            bnb_discount_detected = True

    # =====================================================
    # Fee reserve safety test.
    # =====================================================

    planned_buys = sum(
        (
            line.estimated_notional
            for line in funding.buys
        ),
        ZERO,
    )

    planned_sells = sum(
        (
            line.estimated_notional
            for line in funding.sells
        ),
        ZERO,
    )

    planned_turnover = (
        planned_buys
        + planned_sells
    )

    taker_rate = Decimal(
        str(
            account.get(
                "commissionRates",
                {},
            ).get(
                "taker",
                "0",
            )
        )
    )

    required_fee_buffer = (
        planned_turnover
        * taker_rate
        * fee_buffer_multiplier
    )

    if bnb_discount_detected:

        bnb_book = books[
            f"BNB{base_currency}"
        ]

        bnb_mid = (
            bnb_book["bid"]
            + bnb_book["ask"]
        ) / Decimal("2")

        dedicated_bnb_fee_reserve_value = (
            dedicated_bnb_fee_reserve
            * bnb_mid
        )

        if (
            dedicated_bnb_fee_reserve_value
            < required_fee_buffer
        ):
            raise RuntimeError(
                "Dedicated BNB fee reserve "
                "is insufficient for the "
                "planned executable turnover. "
                f"reserve_bnb="
                f"{dedicated_bnb_fee_reserve}, "
                f"reserve_value="
                f"{dedicated_bnb_fee_reserve_value}, "
                f"required="
                f"{required_fee_buffer}"
            )

    # =====================================================
    # Binance account balance safety checks.
    # =====================================================

    exchange_free_quote = (
        get_free_balance(
            account,
            base_currency,
        )
    )

    # SELLs may only use ETF-owned quantity,
    # but Binance also needs that quantity free.
    for line in plan.sells:

        exchange_free_asset = (
            get_free_balance(
                account,
                line.asset,
            )
        )

        required_quantity = (
            line.order_quantity
            or ZERO
        )

        if (
            exchange_free_asset
            < required_quantity
        ):
            raise RuntimeError(
                f"{line.asset}: Binance free "
                f"balance insufficient for ETF "
                f"SELL. "
                f"free={exchange_free_asset}, "
                f"required="
                f"{required_quantity}"
            )

    # =====================================================
    # Execution ordering:
    #
    # 1 SELLs
    # 2 BNB BUY
    # 3 remaining BUYs
    # =====================================================

    sells = list(funding.sells)
    buys = list(funding.buys)

    buys.sort(
        key=lambda line: (
            0
            if line.asset == "BNB"
            else 1,
            line.asset,
        )
    )

    execution_lines = (
        sells
        + buys
    )

    # =====================================================
    # Display final plan.
    # =====================================================

    print("=" * 92)
    print("FULL ETF REBALANCE")
    print("=" * 92)

    print()
    print(
        f"Feed cutoff       : "
        f"{feed.cutoff_utc}"
    )

    print(
        f"Index level       : "
        f"{feed.index_level}"
    )

    print(
        f"NAV before        : "
        f"{plan.nav:.8f} "
        f"{base_currency}"
    )

    print(
        f"ETF cash          : "
        f"{cash:.8f} "
        f"{base_currency}"
    )

    print(
        f"Orders            : "
        f"{len(execution_lines)}"
    )

    print(
        f"BUY notional      : "
        f"{planned_buys:.8f} "
        f"{base_currency}"
    )

    print(
        f"SELL notional     : "
        f"{planned_sells:.8f} "
        f"{base_currency}"
    )

    print(
        f"Fee buffer req.   : "
        f"{required_fee_buffer:.8f} "
        f"{base_currency}"
    )

    print()
    print("EXECUTION ORDER")
    print("-" * 92)

    for number, line in enumerate(
        execution_lines,
        start=1,
    ):

        if (
            line.quote_order_qty
            is not None
        ):
            amount = (
                f"quoteOrderQty="
                f"{line.quote_order_qty}"
            )
        else:
            amount = (
                f"quantity="
                f"{line.order_quantity}"
            )

        print(
            f"{number:02d} "
            f"{line.symbol:12} "
            f"{line.action:4} "
            f"{amount}"
        )

    print("-" * 92)

    print()
    print(
        "All Binance order preflights: OK"
    )

    if bnb_discount_detected:
        print(
            "Dedicated BNB fee reserve    : OK"
        )

        print(
            "Dedicated reserve value      : "
            f"{dedicated_bnb_fee_reserve_value:.8f} "
            f"{base_currency}"
        )

    # =====================================================
    # Dry run stops here.
    # =====================================================

    if not args.execute_full_rebalance:

        print()
        print(
            "EXECUTION NOT REQUESTED."
        )

        print(
            "No Binance order was sent."
        )

        print()
        print(
            "To execute, BOTH are required:"
        )

        print(
            "  BINANCE_TRADING_ENABLED=true"
        )

        print(
            "  --execute-full-rebalance"
        )

        return

    # =====================================================
    # Hard exchange safety gate.
    # =====================================================

    client.assert_execution_ready()

    # =====================================================
    # Create ONE rebalance run.
    # =====================================================

    with database.connection() as conn:

        run_id = (
            accounting.start_rebalance(
                conn,
                cutoff_utc=feed.cutoff_utc,
                index_level=feed.index_level,
                nav_before=plan.nav,
            )
        )

    print()
    print(
        f"Rebalance run ID: "
        f"{run_id}"
    )

    # =====================================================
    # Execute sequentially.
    # Every order must become ACCOUNTED.
    # =====================================================

    for sequence, line in enumerate(
        execution_lines,
        start=1,
    ):

        client_order_id = (
            f"IDXETF_R"
            f"{run_id:06d}_"
            f"{sequence:02d}_"
            f"{line.asset}"
        )

        print()
        print("=" * 92)

        print(
            f"ORDER "
            f"{sequence}/"
            f"{len(execution_lines)} "
            f"{line.symbol} "
            f"{line.action}"
        )

        print("=" * 92)

        # =============================================
        # Live balance check immediately before
        # reserving/sending this order.
        #
        # SELL proceeds from previous orders may fund
        # subsequent BUYs, therefore this check must
        # be sequential rather than global.
        # =============================================

        live_account = (
            client.get_account()
        )

        require_physical_backing(
            ledger=ledger,
            database=database,
            account=live_account,
            base_currency=base_currency,
            dedicated_bnb_fee_reserve=(
                dedicated_bnb_fee_reserve
            ),
            context=(
                f"before {client_order_id}"
            ),
        )

        print(
            "Physical backing: OK"
        )

        if line.action == "BUY":

            live_free_quote = (
                get_free_balance(
                    live_account,
                    base_currency,
                )
            )

            if (
                line.quote_order_qty
                is not None
            ):

                required_quote = (
                    line.quote_order_qty
                )

            else:

                # Conservative fallback for a BUY
                # expressed in base quantity.
                required_quote = (
                    line.estimated_notional
                    * Decimal("1.01")
                )

            print(
                f"Free {base_currency:4}   : "
                f"{live_free_quote}"
            )

            print(
                f"Required quote : "
                f"{required_quote}"
            )

            if (
                live_free_quote
                < required_quote
            ):

                with database.connection() as conn:

                    accounting.finish_rebalance(
                        conn,
                        rebalance_run_id=run_id,
                        status=(
                            "BLOCKED_INSUFFICIENT_BALANCE"
                        ),
                        notes=(
                            f"{line.symbol} BUY: "
                            f"free="
                            f"{live_free_quote}, "
                            f"required="
                            f"{required_quote}"
                        ),
                    )

                raise RuntimeError(
                    "Rebalance stopped: "
                    f"insufficient live "
                    f"{base_currency} balance "
                    f"for {line.symbol}. "
                    f"free={live_free_quote}, "
                    f"required={required_quote}."
                )

        elif line.action == "SELL":

            live_free_asset = (
                get_free_balance(
                    live_account,
                    line.asset,
                )
            )

            required_quantity = (
                line.order_quantity
                or ZERO
            )

            print(
                f"Free {line.asset:4}   : "
                f"{live_free_asset}"
            )

            print(
                f"Required qty   : "
                f"{required_quantity}"
            )

            if (
                live_free_asset
                < required_quantity
            ):

                with database.connection() as conn:

                    accounting.finish_rebalance(
                        conn,
                        rebalance_run_id=run_id,
                        status=(
                            "BLOCKED_INSUFFICIENT_BALANCE"
                        ),
                        notes=(
                            f"{line.symbol} SELL: "
                            f"free="
                            f"{live_free_asset}, "
                            f"required="
                            f"{required_quantity}"
                        ),
                    )

                raise RuntimeError(
                    "Rebalance stopped: "
                    f"insufficient live "
                    f"{line.asset} balance "
                    f"for {line.symbol}. "
                    f"free={live_free_asset}, "
                    f"required="
                    f"{required_quantity}."
                )

        # ---------------------------------------------
        # Reserve and COMMIT locally first.
        # ---------------------------------------------

        with database.connection() as conn:

            local_order_id = (
                repository.reserve_order(
                    conn,
                    rebalance_run_id=(
                        run_id
                    ),
                    client_order_id=(
                        client_order_id
                    ),
                    symbol=line.symbol,
                    asset=line.asset,
                    side=line.action,
                    requested_quantity=(
                        line.order_quantity
                    ),
                    requested_quote_quantity=(
                        line.quote_order_qty
                    ),
                )
            )

        print(
            f"Local order ID : "
            f"{local_order_id}"
        )

        print(
            f"clientOrderId  : "
            f"{client_order_id}"
        )

        # ---------------------------------------------
        # Defensive existence check.
        # ---------------------------------------------

        existing = (
            client.get_order_if_exists(
                symbol=line.symbol,
                client_order_id=(
                    client_order_id
                ),
            )
        )

        if existing is None:

            # =========================================
            # Capture market benchmark BEFORE POST.
            # Commit it before order submission.
            # =========================================

            benchmark_ticker = (
                client.get_book_ticker(
                    line.symbol
                )
            )

            benchmark_bid = Decimal(
                benchmark_ticker[
                    "bidPrice"
                ]
            )

            benchmark_ask = Decimal(
                benchmark_ticker[
                    "askPrice"
                ]
            )

            benchmark_mid = (
                benchmark_bid
                + benchmark_ask
            ) / Decimal("2")

            bnb_mid_usdc = None

            if bnb_discount_detected:

                bnb_symbol = (
                    f"BNB{base_currency}"
                )

                if (
                    line.symbol
                    == bnb_symbol
                ):
                    bnb_mid_usdc = (
                        benchmark_mid
                    )

                else:

                    bnb_ticker = (
                        client.get_book_ticker(
                            bnb_symbol
                        )
                    )

                    bnb_bid = Decimal(
                        bnb_ticker[
                            "bidPrice"
                        ]
                    )

                    bnb_ask = Decimal(
                        bnb_ticker[
                            "askPrice"
                        ]
                    )

                    bnb_mid_usdc = (
                        bnb_bid
                        + bnb_ask
                    ) / Decimal("2")

            with database.connection() as conn:

                benchmark_repository.record(
                    conn,
                    order_id=(
                        local_order_id
                    ),
                    bid=benchmark_bid,
                    ask=benchmark_ask,
                    bnb_mid_usdc=(
                        bnb_mid_usdc
                    ),
                )

            print(
                f"Benchmark     : "
                f"bid={benchmark_bid} "
                f"ask={benchmark_ask} "
                f"mid={benchmark_mid}"
            )

            try:

                if (
                    line.quote_order_qty
                    is not None
                ):

                    response = (
                        client.place_market_order(
                            symbol=line.symbol,
                            side=line.action,
                            client_order_id=(
                                client_order_id
                            ),
                            quote_order_qty=str(
                                line.quote_order_qty
                            ),
                        )
                    )

                else:

                    response = (
                        client.place_market_order(
                            symbol=line.symbol,
                            side=line.action,
                            client_order_id=(
                                client_order_id
                            ),
                            quantity=str(
                                line.order_quantity
                            ),
                        )
                    )

                with database.connection() as conn:

                    repository.mark_exchange_ack(
                        conn,
                        order_id=(
                            local_order_id
                        ),
                        response=response,
                    )

                print(
                    "POST response : received"
                )

            except Exception as exc:

                with database.connection() as conn:

                    repository.mark_submit_unknown(
                        conn,
                        order_id=(
                            local_order_id
                        ),
                        error=str(exc),
                    )

                print(
                    "POST response : UNKNOWN"
                )

                print(
                    f"Error         : "
                    f"{exc}"
                )

                print(
                    "No automatic retry "
                    "will occur."
                )

        else:

            print(
                "Binance already knows "
                "this clientOrderId."
            )

            print(
                "No duplicate POST sent."
            )

        # ---------------------------------------------
        # Reconcile.
        # ---------------------------------------------

        local_order = (
            get_recoverable_order(
                database,
                repository,
                client_order_id,
            )
        )

        reconciler = OrderReconciler(
            database=database,
            client=client,
            base_currency=base_currency,
        )

        result = (
            reconciler.reconcile_order(
                local_order
            )
        )

        print(
            f"Reconcile     : "
            f"{result.result}"
        )

        print(
            f"Status        : "
            f"{result.exchange_status}"
        )

        print(
            f"Fills         : "
            f"{result.fills}"
        )

        # ---------------------------------------------
        # HARD STOP.
        # ---------------------------------------------

        if (
            result.result
            != "ACCOUNTED"
        ):

            with database.connection() as conn:

                accounting.finish_rebalance(
                    conn,
                    rebalance_run_id=(
                        run_id
                    ),
                    status=(
                        "RECOVERY_REQUIRED"
                    ),
                    notes=(
                        f"{client_order_id}: "
                        f"{result.result}"
                    ),
                )

            raise RuntimeError(
                "Rebalance stopped. "
                f"{client_order_id} "
                f"ended as "
                f"{result.result}. "
                "Do not start another "
                "rebalance until recovered."
            )

    # =====================================================
    # Verify no outstanding local lifecycle state.
    # =====================================================

    unresolved = (
        get_recoverable_orders(
            database,
            repository,
        )
    )

    if unresolved:

        raise RuntimeError(
            "Rebalance finished sending "
            "orders but recoverable local "
            "orders remain."
        )

    # =====================================================
    # Fresh final valuation.
    # =====================================================

    final_cash = (
        ledger.get_cash_balance(
            base_currency
        )
    )

    final_positions = get_positions(
        ledger
    )

    # refresh prices
    final_books = {}

    for asset in final_positions:

        symbol = (
            f"{asset}{base_currency}"
        )

        ticker = client.get_book_ticker(
            symbol
        )

        final_books[symbol] = {
            "bid": Decimal(
                ticker["bidPrice"]
            ),
            "ask": Decimal(
                ticker["askPrice"]
            ),
        }

    final_nav, final_market_value = (
        calculate_nav(
            cash=final_cash,
            positions=final_positions,
            books=final_books,
            base_currency=base_currency,
        )
    )

    shares = Decimal(
        ledger.get_meta(
            "shares_outstanding"
        )
    )

    nav_per_share = (
        final_nav
        / shares
    )

    # =====================================================
    # Persist final NAV and complete run.
    # =====================================================

    with database.connection() as conn:

        conn.execute(
            """
            INSERT INTO nav_snapshots (
                timestamp_utc,
                cash_usdc,
                market_value_usdc,
                nav_usdc,
                shares_outstanding,
                nav_per_share_usdc,
                index_level,
                tracking_difference
            )
            VALUES (
                datetime('now'),
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                str(final_cash),
                str(final_market_value),
                str(final_nav),
                str(shares),
                str(nav_per_share),
                str(feed.index_level),
                None,
            ),
        )

        accounting.finish_rebalance(
            conn,
            rebalance_run_id=run_id,
            status="COMPLETED",
            notes=(
                f"{len(execution_lines)} "
                f"orders accounted."
            ),
        )

    # =====================================================
    # Final report
    # =====================================================

    print()
    print("=" * 92)
    print("REBALANCE COMPLETED")
    print("=" * 92)

    print()
    print(
        f"Run ID           : "
        f"{run_id}"
    )

    print(
        f"Orders accounted : "
        f"{len(execution_lines)}"
    )

    print(
        f"Cash             : "
        f"{final_cash:.8f} "
        f"{base_currency}"
    )

    print(
        f"Market value     : "
        f"{final_market_value:.8f} "
        f"{base_currency}"
    )

    print(
        f"NAV              : "
        f"{final_nav:.8f} "
        f"{base_currency}"
    )

    print(
        f"NAV/share        : "
        f"{nav_per_share:.8f} "
        f"{base_currency}"
    )

    print()
    print("ETF POSITIONS")
    print("-" * 92)

    for asset in sorted(
        final_positions
    ):

        print(
            f"{asset:6} "
            f"{final_positions[asset]}"
        )

    print("-" * 92)

    print()
    print(
        "FULL ETF REBALANCE: COMPLETE"
    )


if __name__ == "__main__":
    main()
