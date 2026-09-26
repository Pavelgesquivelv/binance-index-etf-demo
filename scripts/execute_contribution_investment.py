from __future__ import annotations

import argparse
import os
from decimal import Decimal
from pathlib import Path
import sys

from dotenv import load_dotenv
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")


from src.contributions.contribution_investment import (
    build_order_intents,
)
from src.contributions.contribution_planner import (
    ContributionPlanner,
)
from src.contributions.contribution_repository import (
    ContributionRepository,
    STATUS_ACCEPTED,
    STATUS_COMPLETED,
    STATUS_INVESTING,
    STATUS_RECOVERY_REQUIRED,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.execution.benchmark_repository import (
    ExecutionBenchmarkRepository,
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
from src.storage.database import Database


ZERO = Decimal("0")


def env_enabled(name: str) -> bool:

    return (
        os.getenv(
            name,
            "",
        ).strip().lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def load_config() -> dict:

    with (
        ROOT
        / "config"
        / "runtime.yaml"
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
        if Decimal(
            row["quantity"]
        ) != ZERO
    }


def calculate_live_nav(
    *,
    client: BinanceDemoClient,
    cash: Decimal,
    positions: dict[str, Decimal],
    base_currency: str,
) -> tuple[
    Decimal,
    Decimal,
]:

    market_value = ZERO

    for asset, quantity in (
        positions.items()
    ):

        ticker = client.get_book_ticker(
            f"{asset}{base_currency}"
        )

        bid = Decimal(
            ticker["bidPrice"]
        )

        ask = Decimal(
            ticker["askPrice"]
        )

        mid = (
            bid + ask
        ) / Decimal("2")

        market_value += (
            quantity * mid
        )

    return (
        cash + market_value,
        market_value,
    )


def require_backing(
    *,
    ledger: PortfolioLedger,
    database: Database,
    client: BinanceDemoClient,
    account: dict,
    base_currency: str,
    dedicated_bnb_reserve: Decimal,
) -> None:

    cash = ledger.get_cash_balance(
        base_currency
    )

    positions = get_positions(
        ledger
    )

    backing = check_physical_backing(
        cash=cash,
        positions=positions,
        account=account,
        base_currency=base_currency,
        minimum_reserves=(
            build_owned_minimum_reserves_from_database(
                database,
                base_currency=base_currency,
                dedicated_bnb_fee_reserve=(
                    dedicated_bnb_reserve
                ),
            )
        ),
    )

    if not backing.ok:

        details = ", ".join(
            (
                f"{line.asset}:"
                f"{-line.surplus}"
            )
            for line in backing.deficits
        )

        raise RuntimeError(
            "Physical backing failed: "
            f"{details}"
        )


def mark_recovery(
    *,
    database: Database,
    repository: ContributionRepository,
    contribution_id: int,
    message: str,
) -> None:

    with database.connection() as conn:

        repository.mark_recovery_required(
            conn,
            contribution_id=(
                contribution_id
            ),
            notes=message,
        )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--period-id",
        required=True,
    )

    parser.add_argument(
        "--execute-contribution-investment",
        action="store_true",
    )

    args = parser.parse_args()

    config = load_config()

    contribution_cfg = (
        config["cash_contributions"]
    )

    base_currency = (
        contribution_cfg["currency"]
        .upper()
    )

    max_orders = int(
        contribution_cfg[
            "execution"
        ]["max_orders"]
    )

    fee_buffer_multiplier = Decimal(
        str(
            contribution_cfg[
                "execution"
            ][
                "fee_buffer_multiplier"
            ]
        )
    )

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

    contribution_repository = (
        ContributionRepository()
    )

    order_repository = (
        OrderRepository()
    )

    benchmark_repository = (
        ExecutionBenchmarkRepository()
    )

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    calendar_state = (
        classify_feed_cutoff(
            feed.cutoff_utc
        )
    )

    with database.connection() as conn:

        contribution = conn.execute(
            """
            SELECT *
            FROM cash_contributions
            WHERE period_id = ?
            """,
            (
                args.period_id,
            ),
        ).fetchone()

        completed_run = conn.execute(
            """
            SELECT id
            FROM rebalance_runs
            WHERE cutoff_utc = ?
              AND status = 'COMPLETED'
            ORDER BY id DESC
            LIMIT 1
            """,
            (
                feed.cutoff_utc,
            ),
        ).fetchone()

    if contribution is None:

        raise RuntimeError(
            "Contribution period not found: "
            f"{args.period_id}"
        )

    contribution = dict(
        contribution
    )

    contribution_id = int(
        contribution["id"]
    )

    status = contribution[
        "status"
    ]

    if status == STATUS_COMPLETED:

        print(
            "Decision           : "
            "NO_ACTION_ALREADY_COMPLETED"
        )

        return

    if status == STATUS_RECOVERY_REQUIRED:

        raise RuntimeError(
            "Contribution requires manual "
            "recovery before execution."
        )

    if status not in {
        STATUS_ACCEPTED,
        STATUS_INVESTING,
    }:

        raise RuntimeError(
            "Contribution is not ready "
            "for investment. "
            f"status={status}"
        )

    if (
        calendar_state.status
        == WAITING_FOR_MONTH_END_FEED
    ):

        raise RuntimeError(
            "Contribution investment blocked: "
            "month-end transition window is "
            "active and the new monthly "
            "portfolio feed is not yet ready."
        )

    if (
        calendar_state.status
        == STALE_MISSING_MONTHLY_REBALANCE
    ):

        raise RuntimeError(
            "Contribution investment blocked: "
            "the expected monthly portfolio "
            "feed is missing."
        )

    if (
        calendar_state.status
        == FUTURE_INVALID
    ):

        raise RuntimeError(
            "Contribution investment blocked: "
            "portfolio feed cutoff is invalid "
            "for the current monthly calendar."
        )

    if (
        calendar_state.status
        != CURRENT
    ):

        raise RuntimeError(
            "Contribution investment blocked: "
            "unknown feed calendar state: "
            f"{calendar_state.status}"
        )

    if completed_run is None:

        raise RuntimeError(
            "Current index portfolio has "
            "not been processed."
        )

    if (
        contribution[
            "feed_cutoff_utc"
        ]
        != feed.cutoff_utc
    ):

        raise RuntimeError(
            "Portfolio cutoff changed after "
            "contribution acceptance."
        )

    amount = Decimal(
        contribution[
            "accepted_amount"
        ]
    )

    if amount <= ZERO:

        raise RuntimeError(
            "Accepted amount must "
            "be positive."
        )

    with database.connection() as conn:

        recoverable = (
            order_repository
            .get_recoverable_orders(
                conn
            )
        )

    foreign_recoverable = [
        row
        for row in recoverable
        if row.get(
            "contribution_id"
        ) != contribution_id
    ]

    if foreign_recoverable:

        raise RuntimeError(
            "Execution blocked: recoverable "
            "orders belonging to another "
            "rebalance/contribution exist."
        )

    client = BinanceDemoClient()

    account = client.get_account()

    dedicated_bnb_reserve = Decimal(
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

    require_backing(
        ledger=ledger,
        database=database,
        client=client,
        account=account,
        base_currency=base_currency,
        dedicated_bnb_reserve=(
            dedicated_bnb_reserve
        ),
    )

    plan = ContributionPlanner().build(
        feed=feed,
        amount=amount,
        currency=base_currency,
        period_id=args.period_id,
    )

    intents = build_order_intents(
        plan=plan,
        base_currency=base_currency,
        order_prefix=(
            config["fund"][
                "order_prefix"
            ]
        ),
    )

    if len(intents) > max_orders:

        raise RuntimeError(
            "Contribution contains too "
            "many orders."
        )

    bnb_discount_detected = False

    for intent in intents:

        response = (
            client.test_market_order(
                symbol=intent.symbol,
                side="BUY",
                quote_order_qty=str(
                    intent.quote_order_qty
                ),
                compute_commission_rates=True,
            )
        )

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

    turnover = sum(
        (
            intent.quote_order_qty
            for intent in intents
        ),
        ZERO,
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

    fee_buffer = (
        turnover
        * taker_rate
        * fee_buffer_multiplier
    )

    shared_reserve_value = None

    if bnb_discount_detected:

        ticker = client.get_book_ticker(
            f"BNB{base_currency}"
        )

        bid = Decimal(
            ticker["bidPrice"]
        )

        ask = Decimal(
            ticker["askPrice"]
        )

        bnb_mid = (
            bid + ask
        ) / Decimal("2")

        shared_reserve_value = (
            dedicated_bnb_reserve
            * bnb_mid
        )

        if (
            shared_reserve_value
            < fee_buffer
        ):

            raise RuntimeError(
                "Dedicated BNB fee reserve "
                "is insufficient."
            )

    print("=" * 100)

    print(
        "ETF CONTRIBUTION INVESTMENT"
    )

    print("=" * 100)

    print()

    print(
        f"Period             : "
        f"{args.period_id}"
    )

    print(
        f"Contribution ID    : "
        f"{contribution_id}"
    )

    print(
        f"Status             : "
        f"{status}"
    )

    print(
        f"Amount             : "
        f"{amount:.8f} "
        f"{base_currency}"
    )

    print(
        f"Orders             : "
        f"{len(intents)}"
    )

    print(
        f"BUY notional       : "
        f"{turnover:.8f} "
        f"{base_currency}"
    )

    print(
        f"SELL notional      : "
        f"{ZERO:.8f} "
        f"{base_currency}"
    )

    print(
        f"Fee buffer         : "
        f"{fee_buffer:.8f} "
        f"{base_currency}"
    )

    print()

    for intent in intents:

        print(
            f"{intent.sequence:02d} "
            f"{intent.client_order_id:30} "
            f"{intent.symbol:12} "
            f"BUY "
            f"{intent.quote_order_qty} "
            f"{base_currency}"
        )

    print()

    print(
        "All Binance preflights : OK"
    )

    print(
        "Physical backing       : OK"
    )

    print(
        "BUY-only invariant      : OK"
    )

    if not (
        args
        .execute_contribution_investment
    ):

        print()

        print(
            "Decision           : "
            "READY_FOR_EXECUTION"
        )

        print(
            "DRY RUN ONLY."
        )

        print(
            "No SQLite mutation."
        )

        print(
            "No Binance order was sent."
        )

        return

    if not env_enabled(
        "ETF_CONTRIBUTION_EXECUTION_ENABLED"
    ):

        raise RuntimeError(
            "Contribution execution blocked: "
            "ETF_CONTRIBUTION_EXECUTION_ENABLED "
            "is not true."
        )

    client.assert_execution_ready()

    with database.connection() as conn:

        contribution_repository\
            .mark_investment_in_progress(
                conn,
                contribution_id=(
                    contribution_id
                ),
            )

    reconciler = OrderReconciler(
        database=database,
        client=client,
        base_currency=base_currency,
    )

    for intent in intents:

        print()
        print("=" * 100)

        print(
            f"ORDER "
            f"{intent.sequence}/"
            f"{len(intents)} "
            f"{intent.symbol}"
        )

        print("=" * 100)

        with database.connection() as conn:

            local_order = (
                order_repository
                .get_by_client_order_id(
                    conn,
                    intent.client_order_id,
                )
            )

        if local_order is not None:

            if (
                local_order[
                    "contribution_id"
                ]
                != contribution_id
                or local_order[
                    "rebalance_run_id"
                ]
                is not None
            ):

                raise RuntimeError(
                    "Existing order has "
                    "unexpected ownership."
                )

            if (
                local_order["symbol"]
                != intent.symbol
                or local_order["side"]
                != "BUY"
            ):

                raise RuntimeError(
                    "Existing order does not "
                    "match contribution intent."
                )

            requested_quote = Decimal(
                local_order[
                    "requested_quote_quantity"
                ]
            )

            if (
                requested_quote
                != intent.quote_order_qty
            ):

                raise RuntimeError(
                    "Existing order quote "
                    "amount mismatch."
                )

            if (
                local_order[
                    "local_status"
                ]
                == "ACCOUNTED"
            ):

                if (
                    local_order[
                        "exchange_status"
                    ]
                    != "FILLED"
                    or Decimal(
                        local_order[
                            "executed_quantity"
                        ]
                        or "0"
                    )
                    <= ZERO
                ):

                    mark_recovery(
                        database=database,
                        repository=(
                            contribution_repository
                        ),
                        contribution_id=(
                            contribution_id
                        ),
                        message=(
                            "Accounted contribution "
                            "order was not a positive "
                            "FILLED execution."
                        ),
                    )

                    raise RuntimeError(
                        "Contribution requires "
                        "manual recovery."
                    )

                print(
                    "Already ACCOUNTED."
                )

                continue

            result = (
                reconciler.reconcile_order(
                    local_order
                )
            )

            print(
                f"Reconcile     : "
                f"{result.result}"
            )

            if (
                result.result == "ACCOUNTED"
                and result.exchange_status
                == "FILLED"
            ):
                continue

            mark_recovery(
                database=database,
                repository=(
                    contribution_repository
                ),
                contribution_id=(
                    contribution_id
                ),
                message=(
                    f"{intent.client_order_id}: "
                    f"{result.result}"
                ),
            )

            raise RuntimeError(
                "Existing contribution order "
                "could not be safely completed. "
                "No automatic re-POST will occur."
            )

        live_account = (
            client.get_account()
        )

        require_backing(
            ledger=ledger,
            database=database,
            client=client,
            account=live_account,
            base_currency=base_currency,
            dedicated_bnb_reserve=(
                dedicated_bnb_reserve
            ),
        )

        free_quote = get_free_balance(
            live_account,
            base_currency,
        )

        if (
            free_quote
            < intent.quote_order_qty
        ):

            raise RuntimeError(
                f"Insufficient live "
                f"{base_currency}: "
                f"free={free_quote}, "
                f"required="
                f"{intent.quote_order_qty}"
            )

        with database.connection() as conn:

            local_order_id = (
                order_repository.reserve_order(
                    conn,
                    contribution_id=(
                        contribution_id
                    ),
                    client_order_id=(
                        intent.client_order_id
                    ),
                    symbol=intent.symbol,
                    asset=intent.asset,
                    side="BUY",
                    requested_quantity=None,
                    requested_quote_quantity=(
                        intent.quote_order_qty
                    ),
                )
            )

        ticker = client.get_book_ticker(
            intent.symbol
        )

        benchmark_bid = Decimal(
            ticker["bidPrice"]
        )

        benchmark_ask = Decimal(
            ticker["askPrice"]
        )

        benchmark_mid = (
            benchmark_bid
            + benchmark_ask
        ) / Decimal("2")

        bnb_mid_usdc = None

        if bnb_discount_detected:

            if (
                intent.symbol
                == f"BNB{base_currency}"
            ):
                bnb_mid_usdc = (
                    benchmark_mid
                )

            else:

                bnb_ticker = (
                    client.get_book_ticker(
                        f"BNB{base_currency}"
                    )
                )

                bnb_mid_usdc = (
                    Decimal(
                        bnb_ticker[
                            "bidPrice"
                        ]
                    )
                    + Decimal(
                        bnb_ticker[
                            "askPrice"
                        ]
                    )
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

        existing_exchange = (
            client.get_order_if_exists(
                symbol=intent.symbol,
                client_order_id=(
                    intent.client_order_id
                ),
            )
        )

        if existing_exchange is None:

            try:

                response = (
                    client.place_market_order(
                        symbol=intent.symbol,
                        side="BUY",
                        client_order_id=(
                            intent.client_order_id
                        ),
                        quote_order_qty=str(
                            intent
                            .quote_order_qty
                        ),
                    )
                )

                with database.connection() as conn:

                    order_repository\
                        .mark_exchange_ack(
                            conn,
                            order_id=(
                                local_order_id
                            ),
                            response=response,
                        )

            except Exception as exc:

                with database.connection() as conn:

                    order_repository\
                        .mark_submit_unknown(
                            conn,
                            order_id=(
                                local_order_id
                            ),
                            error=str(exc),
                        )

        with database.connection() as conn:

            local_order = (
                order_repository
                .get_by_client_order_id(
                    conn,
                    intent.client_order_id,
                )
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

        if (
            result.result != "ACCOUNTED"
            or result.exchange_status
            != "FILLED"
        ):

            mark_recovery(
                database=database,
                repository=(
                    contribution_repository
                ),
                contribution_id=(
                    contribution_id
                ),
                message=(
                    f"{intent.client_order_id}: "
                    f"{result.result}"
                ),
            )

            raise RuntimeError(
                "Contribution execution "
                "stopped. Manual recovery "
                "required."
            )

    with database.connection() as conn:

        unresolved = (
            order_repository
            .get_recoverable_orders(
                conn
            )
        )

        rows = conn.execute(
            """
            SELECT
                o.client_order_id,
                o.exchange_status,
                o.executed_quantity,
                l.local_status
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE o.contribution_id = ?
            ORDER BY o.id
            """,
            (
                contribution_id,
            ),
        ).fetchall()

    if unresolved:

        raise RuntimeError(
            "Recoverable ETF orders remain "
            "after contribution execution."
        )

    expected_ids = {
        intent.client_order_id
        for intent in intents
    }

    actual_ids = {
        row["client_order_id"]
        for row in rows
    }

    if actual_ids != expected_ids:

        raise RuntimeError(
            "Contribution order set does "
            "not match expected plan."
        )

    for row in rows:

        if (
            row["local_status"]
            != "ACCOUNTED"
            or row["exchange_status"]
            != "FILLED"
            or Decimal(
                row[
                    "executed_quantity"
                ]
                or "0"
            )
            <= ZERO
        ):

            raise RuntimeError(
                "Contribution contains "
                "non-successful order state."
            )

    final_cash = (
        ledger.get_cash_balance(
            base_currency
        )
    )

    final_positions = get_positions(
        ledger
    )

    (
        final_nav,
        final_market_value,
    ) = calculate_live_nav(
        client=client,
        cash=final_cash,
        positions=final_positions,
        base_currency=base_currency,
    )

    shares = Decimal(
        ledger.get_meta(
            "shares_outstanding"
        )
    )

    nav_per_share = (
        final_nav / shares
    )

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

        contribution_repository\
            .mark_completed(
                conn,
                contribution_id=(
                    contribution_id
                ),
                notes=(
                    f"{len(intents)} "
                    "BUY orders accounted."
                ),
            )

    print()
    print("=" * 100)

    print(
        "CONTRIBUTION INVESTMENT COMPLETED"
    )

    print("=" * 100)

    print()

    print(
        f"Orders accounted : "
        f"{len(intents)}"
    )

    print(
        f"Cash             : "
        f"{final_cash:.8f} "
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

    print(
        "Contribution status: COMPLETED"
    )


if __name__ == "__main__":
    main()
