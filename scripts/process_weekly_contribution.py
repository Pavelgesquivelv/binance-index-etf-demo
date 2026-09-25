from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_repository import (
    ContributionRepository,
    STATUS_ACCEPTED,
    STATUS_COMPLETED,
)
from src.contributions.contribution_schedule import (
    resolve_weekly_period,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.portfolio.physical_backing import (
    check_physical_backing,
)
from src.storage.database import (
    Database,
)


ZERO = Decimal("0")


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


def free_balance(
    account: dict,
    asset: str,
) -> Decimal:

    for row in account.get(
        "balances",
        [],
    ):

        if row["asset"] == asset:

            return Decimal(
                row["free"]
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

        symbol = (
            f"{asset}{base_currency}"
        )

        ticker = (
            client.get_book_ticker(
                symbol
            )
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


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--accept-only",
        action="store_true",
        help=(
            "Accept the weekly physical "
            "USDC contribution and issue "
            "new ETF shares. Never sends "
            "Binance orders."
        ),
    )

    args = parser.parse_args()

    config = load_config()

    contribution_cfg = (
        config["cash_contributions"]
    )

    if not contribution_cfg["enabled"]:

        print(
            "Decision           : "
            "NO_ACTION_DISABLED"
        )

        return

    # -------------------------------------------------
    # Configuration invariants.
    # -------------------------------------------------

    investment_cfg = (
        contribution_cfg["investment"]
    )

    if (
        investment_cfg["allow_sells"]
        is not False
    ):
        raise RuntimeError(
            "Contribution configuration "
            "must have allow_sells=false."
        )

    if (
        investment_cfg["trigger_rebalance"]
        is not False
    ):
        raise RuntimeError(
            "Contribution configuration "
            "must have "
            "trigger_rebalance=false."
        )

    currency = (
        contribution_cfg[
            "currency"
        ].upper()
    )

    amount = Decimal(
        str(
            contribution_cfg["amount"]
        )
    )

    schedule = (
        contribution_cfg["schedule"]
    )

    now_utc = datetime.now(
        timezone.utc
    )

    period = resolve_weekly_period(
        now_utc=now_utc,
        timezone_name=(
            schedule["timezone"]
        ),
        weekday=(
            schedule["weekday"]
        ),
        time_local=(
            schedule["time_local"]
        ),
        start_date_local=(
            schedule[
                "start_date_local"
            ]
        ),
    )

    print("=" * 94)

    print(
        "ETF WEEKLY CONTRIBUTION "
        "PROCESSOR"
    )

    print("=" * 94)

    print()

    if period is None:

        print(
            "Decision           : "
            "NO_ACTION_NOT_STARTED"
        )

        print(
            "First contribution : "
            f"{schedule['start_date_local']} "
            f"{schedule['time_local']} "
            f"{schedule['timezone']}"
        )

        return

    print(
        f"Period             : "
        f"{period.period_id}"
    )

    print(
        f"Scheduled local    : "
        f"{period.scheduled_local.isoformat()}"
    )

    print(
        f"Scheduled UTC      : "
        f"{period.scheduled_utc.isoformat()}"
    )

    if not period.is_due:

        print()

        print(
            "Decision           : "
            "NO_ACTION_NOT_DUE"
        )

        return

    database = Database(
        str(
            ROOT
            / config["storage"][
                "database"
            ]
        )
    )

    repository = (
        ContributionRepository()
    )

    ledger = PortfolioLedger(
        database
    )

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    # -------------------------------------------------
    # Persistent state checks.
    # -------------------------------------------------

    with database.connection() as conn:

        repository.ensure_schema(conn)

        existing = (
            repository.get_by_period(
                conn,
                period.period_id,
            )
        )

        completed_run = (
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
                (
                    feed.cutoff_utc,
                ),
            ).fetchone()
        )

        recoverable_count = (
            conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM orders o
                JOIN order_lifecycle l
                  ON l.order_id = o.id
                WHERE l.local_status
                      <> 'ACCOUNTED'
                """
            ).fetchone()["n"]
        )

    if (
        existing is not None
        and existing["status"]
        in {
            STATUS_ACCEPTED,
            STATUS_COMPLETED,
        }
    ):

        print()

        print(
            "Decision           : "
            "NO_ACTION_ALREADY_ACCEPTED"
        )

        print(
            f"Existing status    : "
            f"{existing['status']}"
        )

        return

    if completed_run is None:

        print()

        print(
            "Decision           : "
            "BLOCKED_PORTFOLIO_NOT_PROCESSED"
        )

        print(
            f"Feed cutoff        : "
            f"{feed.cutoff_utc}"
        )

        raise SystemExit(2)

    if recoverable_count:

        print()

        print(
            "Decision           : "
            "BLOCKED_RECOVERY_REQUIRED"
        )

        print(
            f"Recoverable orders : "
            f"{recoverable_count}"
        )

        raise SystemExit(2)

    # -------------------------------------------------
    # ETF ownership state.
    # -------------------------------------------------

    cash_before = (
        ledger.get_cash_balance(
            currency
        )
    )

    positions = get_positions(
        ledger
    )

    shares_before = Decimal(
        ledger.get_meta(
            "shares_outstanding"
        )
    )

    # -------------------------------------------------
    # Binance physical state.
    # -------------------------------------------------

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

    backing = check_physical_backing(
        cash=cash_before,
        positions=positions,
        account=account,
        base_currency=currency,
        minimum_reserves={
            "BNB":
                dedicated_bnb_reserve,
        },
    )

    if not backing.ok:

        print()

        print(
            "Decision           : "
            "BLOCKED_PHYSICAL_BACKING"
        )

        for line in backing.deficits:

            print(
                f"{line.asset}: "
                f"deficit="
                f"{-line.surplus}"
            )

        raise SystemExit(2)

    exchange_free_cash = (
        free_balance(
            account,
            currency,
        )
    )

    detected_new_cash = max(
        exchange_free_cash
        - cash_before,
        ZERO,
    )

    print()

    print(
        f"ETF ledger cash    : "
        f"{cash_before:.8f} "
        f"{currency}"
    )

    print(
        f"Binance free cash  : "
        f"{exchange_free_cash:.8f} "
        f"{currency}"
    )

    print(
        f"Detected new cash  : "
        f"{detected_new_cash:.8f} "
        f"{currency}"
    )

    print(
        f"Required           : "
        f"{amount:.8f} "
        f"{currency}"
    )

    if detected_new_cash < amount:

        missing = (
            amount
            - detected_new_cash
        )

        print()

        print(
            "Decision           : "
            "PENDING_PHYSICAL_FUNDS"
        )

        print(
            f"Missing            : "
            f"{missing:.8f} "
            f"{currency}"
        )

        if args.accept_only:

            with database.connection() as conn:

                repository.record_pending(
                    conn,
                    period_id=(
                        period.period_id
                    ),
                    scheduled_at_utc=(
                        period
                        .scheduled_utc
                        .isoformat()
                    ),
                    currency=currency,
                    expected_amount=amount,
                    detected_amount=(
                        detected_new_cash
                    ),
                    feed_cutoff_utc=(
                        feed.cutoff_utc
                    ),
                    notes=(
                        "Waiting for full "
                        "physical contribution."
                    ),
                )

            print(
                "Pending state recorded."
            )

        else:

            print(
                "DRY RUN - no SQLite mutation."
            )

        print(
            "No Binance order was sent."
        )

        return

    # -------------------------------------------------
    # Live pre-contribution valuation.
    # -------------------------------------------------

    (
        nav_before,
        market_value_before,
    ) = calculate_live_nav(
        client=client,
        cash=cash_before,
        positions=positions,
        base_currency=currency,
    )

    if nav_before <= ZERO:

        raise RuntimeError(
            "Live NAV must be positive."
        )

    if shares_before <= ZERO:

        raise RuntimeError(
            "shares_outstanding must "
            "be positive."
        )

    nav_per_share_before = (
        nav_before
        / shares_before
    )

    shares_to_issue = (
        amount
        / nav_per_share_before
    )

    shares_after = (
        shares_before
        + shares_to_issue
    )

    nav_after = (
        nav_before
        + amount
    )

    nav_per_share_after = (
        nav_after
        / shares_after
    )

    print()

    print(
        "Physical backing   : OK"
    )

    print(
        "Physical cash      : OK"
    )

    print()

    print(
        f"NAV before         : "
        f"{nav_before:.8f} "
        f"{currency}"
    )

    print(
        f"Market value       : "
        f"{market_value_before:.8f} "
        f"{currency}"
    )

    print(
        f"Shares before      : "
        f"{shares_before}"
    )

    print(
        f"NAV/share before   : "
        f"{nav_per_share_before:.8f} "
        f"{currency}"
    )

    print(
        f"Shares to issue    : "
        f"{shares_to_issue}"
    )

    print(
        f"Shares after       : "
        f"{shares_after}"
    )

    print(
        f"NAV after cash     : "
        f"{nav_after:.8f} "
        f"{currency}"
    )

    print(
        f"NAV/share after    : "
        f"{nav_per_share_after:.8f} "
        f"{currency}"
    )

    print()

    if not args.accept_only:

        print(
            "Decision           : "
            "READY_FOR_ACCEPTANCE"
        )

        print()

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

    # -------------------------------------------------
    # Atomic contribution acceptance.
    #
    # NO Binance orders occur below this point.
    # -------------------------------------------------

    with database.connection() as conn:

        result = (
            repository.accept_contribution(
                conn,
                period_id=(
                    period.period_id
                ),
                scheduled_at_utc=(
                    period
                    .scheduled_utc
                    .isoformat()
                ),
                currency=currency,
                amount=amount,
                detected_amount=(
                    detected_new_cash
                ),
                feed_cutoff_utc=(
                    feed.cutoff_utc
                ),
                cash_before=(
                    cash_before
                ),
                market_value_before=(
                    market_value_before
                ),
                nav_before=(
                    nav_before
                ),
                nav_per_share_before=(
                    nav_per_share_before
                ),
                shares_before=(
                    shares_before
                ),
                index_level=(
                    feed.index_level
                ),
            )
        )

    # -------------------------------------------------
    # Post-commit verification.
    # -------------------------------------------------

    cash_after_check = (
        ledger.get_cash_balance(
            currency
        )
    )

    shares_after_check = Decimal(
        ledger.get_meta(
            "shares_outstanding"
        )
    )

    expected_cash_after = (
        cash_before
        + amount
    )

    if (
        cash_after_check
        != expected_cash_after
    ):
        raise RuntimeError(
            "Post-acceptance cash "
            "verification failed."
        )

    if (
        shares_after_check
        != result["shares_after"]
    ):
        raise RuntimeError(
            "Post-acceptance share "
            "verification failed."
        )

    print()

    print(
        "Decision           : "
        "ACCEPTED_PENDING_INVESTMENT"
    )

    print(
        f"Accepted amount    : "
        f"{amount:.8f} "
        f"{currency}"
    )

    print(
        f"Cash after         : "
        f"{cash_after_check:.8f} "
        f"{currency}"
    )

    print(
        f"Shares issued      : "
        f"{result['shares_issued']}"
    )

    print(
        f"Shares outstanding : "
        f"{shares_after_check}"
    )

    print()

    print(
        "Contribution accounting committed."
    )

    print(
        "NO investment orders were sent."
    )


if __name__ == "__main__":
    main()
