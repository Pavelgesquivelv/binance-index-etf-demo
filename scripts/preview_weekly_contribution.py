from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_planner import (
    ContributionPlanner,
)
from src.contributions.contribution_schedule import (
    resolve_weekly_period,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
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


def live_nav(
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
        "--simulate-new-cash",
        type=Decimal,
        default=None,
        help=(
            "Dry-run only. Override detected "
            "new physical cash for testing. "
            "Does not modify Binance or SQLite."
        ),
    )

    parser.add_argument(
        "--preview-next-period",
        action="store_true",
        help=(
            "Preview the configured first/next "
            "weekly contribution even when it "
            "is not due yet."
        ),
    )

    args = parser.parse_args()

    config = load_config()

    contribution = config[
        "cash_contributions"
    ]

    if not contribution["enabled"]:
        print(
            "CONTRIBUTIONS DISABLED"
        )
        return

    currency = contribution[
        "currency"
    ].upper()

    amount = Decimal(
        str(
            contribution["amount"]
        )
    )

    schedule = contribution[
        "schedule"
    ]

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

    # Before first contribution date, allow a
    # deterministic preview of the configured
    # first period.
    if (
        period is None
        and args.preview_next_period
    ):

        from datetime import (
            date,
            datetime as dt,
            time as dtime,
        )
        from zoneinfo import ZoneInfo

        start_date = date.fromisoformat(
            schedule[
                "start_date_local"
            ]
        )

        hh, mm = (
            int(x)
            for x in schedule[
                "time_local"
            ].split(":")
        )

        tz = ZoneInfo(
            schedule["timezone"]
        )

        scheduled_local = dt.combine(
            start_date,
            dtime(
                hour=hh,
                minute=mm,
            ),
            tzinfo=tz,
        )

        iso = (
            start_date.isocalendar()
        )

        class PreviewPeriod:
            pass

        period = PreviewPeriod()

        period.period_id = (
            f"{iso.year}-W"
            f"{iso.week:02d}"
        )

        period.scheduled_local = (
            scheduled_local
        )

        period.scheduled_utc = (
            scheduled_local.astimezone(
                timezone.utc
            )
        )

        period.is_due = False

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

    if (
        not period.is_due
        and not args.preview_next_period
    ):

        print(
            "Decision           : "
            "NO_ACTION_NOT_DUE"
        )

        print(
            "Period             : "
            f"{period.period_id}"
        )

        print(
            "Scheduled local    : "
            f"{period.scheduled_local.isoformat()}"
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

    ledger = PortfolioLedger(
        database
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

    if (
        calendar_state.status
        == WAITING_FOR_MONTH_END_FEED
    ):

        print(
            "Decision           : "
            "BLOCKED_WAITING_FOR_MONTH_END_FEED"
        )

        print(
            f"Feed cutoff        : "
            f"{feed.cutoff_utc}"
        )

        print(
            f"Expected cutoff    : "
            f"{calendar_state.expected_cutoff_local.isoformat()}"
        )

        raise SystemExit(2)

    if (
        calendar_state.status
        == STALE_MISSING_MONTHLY_REBALANCE
    ):

        print(
            "Decision           : "
            "BLOCKED_MISSING_MONTHLY_REBALANCE"
        )

        raise SystemExit(2)

    if (
        calendar_state.status
        == FUTURE_INVALID
    ):

        print(
            "Decision           : "
            "BLOCKED_FUTURE_FEED"
        )

        raise SystemExit(2)

    if (
        calendar_state.status
        != CURRENT
    ):

        raise RuntimeError(
            "Unknown feed calendar state: "
            f"{calendar_state.status}"
        )

    # -------------------------------------------------
    # The current index portfolio must already have
    # been successfully processed.
    # -------------------------------------------------

    with database.connection() as conn:

        completed = conn.execute(
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

        recoverable = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE l.local_status
                  <> 'ACCOUNTED'
            """
        ).fetchone()["n"]

        contribution_exists = False

        table_exists = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'cash_contributions'
            """
        ).fetchone()

        if table_exists:

            row = conn.execute(
                """
                SELECT status
                FROM cash_contributions
                WHERE period_id = ?
                """,
                (
                    period.period_id,
                ),
            ).fetchone()

            contribution_exists = (
                row is not None
                and row["status"]
                in {
                    "ACCEPTED_PENDING_INVESTMENT",
                    "COMPLETED",
                }
            )

    if completed is None:

        print(
            "Decision           : "
            "BLOCKED_PORTFOLIO_NOT_PROCESSED"
        )

        print(
            "Feed cutoff        : "
            f"{feed.cutoff_utc}"
        )

        print(
            "The index rebalance must be "
            "processed before accepting "
            "new weekly cash."
        )

        raise SystemExit(2)

    if recoverable:

        print(
            "Decision           : "
            "BLOCKED_RECOVERY_REQUIRED"
        )

        raise SystemExit(2)

    if contribution_exists:

        print(
            "Decision           : "
            "NO_ACTION_ALREADY_ACCEPTED"
        )

        print(
            "Period             : "
            f"{period.period_id}"
        )

        return

    cash = ledger.get_cash_balance(
        currency
    )

    positions = {
        row["asset"]:
            Decimal(row["quantity"])
        for row in ledger.get_positions()
        if Decimal(
            row["quantity"]
        ) != ZERO
    }

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
        cash=cash,
        positions=positions,
        account=account,
        base_currency=currency,
        minimum_reserves={
            "BNB":
                dedicated_bnb_reserve,
        },
    )

    if not backing.ok:

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

    actual_new_cash = max(
        exchange_free_cash - cash,
        ZERO,
    )

    simulated = (
        args.simulate_new_cash
        is not None
    )

    detected_new_cash = (
        args.simulate_new_cash
        if simulated
        else actual_new_cash
    )

    nav_before, market_value = (
        live_nav(
            client=client,
            cash=cash,
            positions=positions,
            base_currency=currency,
        )
    )

    shares_before = Decimal(
        ledger.get_meta(
            "shares_outstanding"
        )
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

    plan = ContributionPlanner().build(
        feed=feed,
        amount=amount,
        currency=currency,
        period_id=period.period_id,
    )

    print("=" * 94)
    print(
        "ETF WEEKLY CONTRIBUTION PREVIEW"
    )
    print("=" * 94)

    print()

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

    print(
        f"Portfolio cutoff   : "
        f"{feed.cutoff_utc}"
    )

    print(
        f"Completed run      : "
        f"{completed['id']}"
    )

    print()

    print(
        f"ETF ledger cash    : "
        f"{cash:.8f} {currency}"
    )

    print(
        f"Binance free cash  : "
        f"{exchange_free_cash:.8f} "
        f"{currency}"
    )

    print(
        f"Actual new cash    : "
        f"{actual_new_cash:.8f} "
        f"{currency}"
    )

    if simulated:

        print(
            f"SIMULATED new cash : "
            f"{detected_new_cash:.8f} "
            f"{currency}"
        )

    print(
        f"Required           : "
        f"{amount:.8f} {currency}"
    )

    print()

    if detected_new_cash < amount:

        print(
            "Decision           : "
            "PENDING_PHYSICAL_FUNDS"
        )

        print(
            "Missing            : "
            f"{amount - detected_new_cash:.8f} "
            f"{currency}"
        )

        print()

        print(
            "No SQLite mutation."
        )

        print(
            "No Binance order was sent."
        )

        return

    print(
        "Physical cash      : OK"
    )

    print(
        "Physical backing   : OK"
    )

    print()

    print(
        f"NAV before         : "
        f"{nav_before:.8f} {currency}"
    )

    print(
        f"Market value       : "
        f"{market_value:.8f} {currency}"
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
        f"{nav_after:.8f} {currency}"
    )

    print(
        f"NAV/share after    : "
        f"{nav_per_share_after:.8f} "
        f"{currency}"
    )

    print()

    print(
        "BUY-ONLY ALLOCATION"
    )

    print("-" * 94)

    for line in plan.allocations:

        print(
            f"{line.asset:6} "
            f"{line.target_weight_pct:>10}% "
            f"BUY "
            f"{line.quote_amount:>14} "
            f"{currency}"
        )

    print("-" * 94)

    print()

    print(
        "Decision           : "
        "READY_FOR_CONTRIBUTION_ACCEPTANCE"
    )

    print()

    if simulated:
        print(
            "SIMULATION ONLY."
        )

    print(
        "No SQLite mutation."
    )

    print(
        "No Binance order was sent."
    )


if __name__ == "__main__":
    main()
