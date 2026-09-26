from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys

import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
from src.portfolio.owned_reserves import (
    build_owned_minimum_reserves_from_database,
)
from src.portfolio.physical_backing import (
    check_physical_backing,
)
from src.storage.database import (
    Database,
)

from src.contributions.interlocks import (
    get_blocking_contributions,
)


load_dotenv(ROOT / ".env")


LOCK_FILE = (
    ROOT
    / "data"
    / "weekly_runner.lock"
)


def load_config() -> dict:
    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:
        return yaml.safe_load(file)


def env_enabled(
    name: str,
) -> bool:

    value = (
        os.getenv(
            name,
            "false",
        )
        .strip()
        .lower()
    )

    return value in {
        "1",
        "true",
        "yes",
        "on",
    }


def acquire_lock() -> int:

    LOCK_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        fd = os.open(
            LOCK_FILE,
            (
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
            ),
        )

    except FileExistsError:

        raise RuntimeError(
            "WEEKLY RUNNER BLOCKED: "
            "another runner lock exists. "
            f"Lock file: {LOCK_FILE}. "
            "Do not delete it until confirming "
            "that no ETF runner is active."
        )

    payload = (
        f"pid={os.getpid()}\n"
        f"created_at_utc="
        f"{datetime.now(timezone.utc).isoformat()}\n"
    )

    os.write(
        fd,
        payload.encode("utf-8"),
    )

    return fd


def release_lock(
    fd: int,
) -> None:

    try:
        os.close(fd)

    finally:
        try:
            LOCK_FILE.unlink()
        except FileNotFoundError:
            pass


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--execute-if-ready",
        action="store_true",
        help=(
            "Execute the full rebalance "
            "only if every weekly safety "
            "condition is satisfied."
        ),
    )

    parser.add_argument(
        "--preview-if-ready",
        action="store_true",
        help=(
            "Run the full rebalance "
            "executor in dry-run mode "
            "when the portfolio is READY."
        ),
    )

    args = parser.parse_args()

    if (
        args.execute_if_ready
        and args.preview_if_ready
    ):
        raise RuntimeError(
            "Choose either "
            "--preview-if-ready or "
            "--execute-if-ready, not both."
        )

    lock_fd = acquire_lock()
    
    try:

        config = load_config()

        database = Database(
            str(
                ROOT
                / config["storage"][
                    "database"
                ]
            )
        )

        # =============================================
        # Load and validate portfolio feed.
        # =============================================

        feed = PortfolioFeedLoader(
            ROOT
            / config["index_feed"][
                "portfolio_file"
            ]
        ).load()

        cutoff = feed.cutoff_utc

        calendar_state = (
            classify_feed_cutoff(
                cutoff
            )
        )

        # =============================================
        # Inspect persistent execution state.
        # =============================================

        with database.connection() as conn:

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
                    (cutoff,),
                ).fetchone()
            )

            unfinished_same_cutoff = (
                conn.execute(
                    """
                    SELECT
                        id,
                        status,
                        started_at_utc,
                        completed_at_utc
                    FROM rebalance_runs
                    WHERE cutoff_utc = ?
                      AND status <> 'COMPLETED'
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (cutoff,),
                ).fetchone()
            )

            recoverable_orders = (
                conn.execute(
                    """
                    SELECT
                        o.client_order_id,
                        l.local_status,
                        o.exchange_status
                    FROM orders o
                    JOIN order_lifecycle l
                      ON l.order_id = o.id
                    WHERE l.local_status
                          <> 'ACCOUNTED'
                    ORDER BY o.id
                    """
                ).fetchall()
            )

            blocking_contributions = (
                get_blocking_contributions(
                    conn
                )
            )

        automation_enabled = (
            env_enabled(
                "ETF_WEEKLY_AUTOMATION_ENABLED"
            )
        )

        trading_enabled = (
            env_enabled(
                "BINANCE_TRADING_ENABLED"
            )
        )

        print("=" * 82)
        print(
            "ETF WEEKLY RUNNER"
        )
        print("=" * 82)

        print()

        print(
            f"Cutoff             : "
            f"{cutoff}"
        )

        print(
            f"Feed calendar state: "
            f"{calendar_state.status}"
        )

        print(
            f"Expected cutoff    : "
            f"{calendar_state.expected_cutoff_local.isoformat()}"
        )

        print(
            f"Grace deadline     : "
            f"{calendar_state.grace_deadline_local.isoformat()}"
        )

        print(
            f"Index level        : "
            f"{feed.index_level}"
        )

        print(
            f"Automation enabled : "
            f"{automation_enabled}"
        )

        print(
            f"Trading enabled    : "
            f"{trading_enabled}"
        )

        print()

        # =============================================
        # State 1:
        # Successfully handled already.
        # This is NORMAL, not an error.
        # =============================================

        if completed_run is not None:

            print(
                "Decision           : "
                "NO_ACTION_ALREADY_COMPLETED"
            )

            print(
                f"Completed run      : "
                f"{completed_run['id']}"
            )

            print(
                f"Completed at       : "
                f"{completed_run['completed_at_utc']}"
            )

            print()

            print(
                "The current portfolio has "
                "already been processed."
            )

            return

        # =============================================
        # State 2:
        # A contribution that has already been
        # accepted must finish investing before
        # a NEW index rebalance can begin.
        # =============================================

        if blocking_contributions:

            print(
                "Decision           : "
                "BLOCKED_CONTRIBUTION_IN_PROGRESS"
            )

            print()
            print(
                "Blocking contributions:"
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

            print()

            print(
                "Complete or recover the "
                "contribution investment before "
                "processing a new index portfolio."
            )

            return

        # =============================================
        # State 3:
        # Any unresolved ETF order blocks automation.
        # =============================================

        if recoverable_orders:

            print(
                "Decision           : "
                "BLOCKED_RECOVERY_REQUIRED"
            )

            print()

            print(
                "Recoverable orders:"
            )

            for row in recoverable_orders:

                print(
                    f"  "
                    f"{row['client_order_id']} "
                    f"local="
                    f"{row['local_status']} "
                    f"exchange="
                    f"{row['exchange_status']}"
                )

            raise RuntimeError(
                "Automatic rebalance blocked "
                "until unresolved ETF orders "
                "are reconciled."
            )

        # =============================================
        # State 3:
        # A previous non-completed run for the same
        # cutoff requires human review.
        # =============================================

        if (
            unfinished_same_cutoff
            is not None
        ):

            print(
                "Decision           : "
                "BLOCKED_EXISTING_RUN"
            )

            print(
                f"Existing run       : "
                f"{unfinished_same_cutoff['id']}"
            )

            print(
                f"Existing status    : "
                f"{unfinished_same_cutoff['status']}"
            )

            raise RuntimeError(
                "A previous non-completed "
                "rebalance exists for this "
                "portfolio cutoff."
            )

        # =============================================
        # State 4:
        # Monthly portfolio calendar validity.
        # =============================================

        if (
            calendar_state.status
            == WAITING_FOR_MONTH_END_FEED
        ):

            print(
                "Decision           : "
                "NO_ACTION_WAITING_FOR_MONTH_END_FEED"
            )

            print()

            print(
                "Month-end transition window "
                "is active. Waiting for the "
                "new monthly portfolio feed."
            )

            return

        if (
            calendar_state.status
            == STALE_MISSING_MONTHLY_REBALANCE
        ):

            print(
                "Decision           : "
                "BLOCKED_MISSING_MONTHLY_REBALANCE"
            )

            raise RuntimeError(
                "The expected monthly portfolio "
                "feed is missing. Refusing to "
                "continue with stale holdings."
            )

        if (
            calendar_state.status
            == FUTURE_INVALID
        ):

            print(
                "Decision           : "
                "BLOCKED_FUTURE_FEED"
            )

            raise RuntimeError(
                "Portfolio feed cutoff is not "
                "valid for the current monthly "
                "index calendar."
            )

        if (
            calendar_state.status
            != CURRENT
        ):

            raise RuntimeError(
                "Unknown feed calendar state: "
                f"{calendar_state.status}"
            )

        # =============================================
        # State 5:
        # Physical backing + dedicated BNB fee reserve.
        #
        # Only required when a new, fresh portfolio
        # could actually become executable.
        # =============================================

        base_currency = (
            config["fund"][
                "base_currency"
            ].upper()
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

        ledger = PortfolioLedger(
            database
        )

        cash = ledger.get_cash_balance(
            base_currency
        )

        positions = {
            row["asset"]:
                Decimal(row["quantity"])
            for row in ledger.get_positions()
            if Decimal(
                row["quantity"]
            ) != 0
        }

        client = BinanceDemoClient()
        account = client.get_account()

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
                        dedicated_bnb_fee_reserve
                    ),
                )
            ),
        )

        if not backing.ok:

            print(
                "Decision           : "
                "BLOCKED_PHYSICAL_BACKING"
            )

            print()

            print(
                "Physical backing deficits:"
            )

            for line in backing.deficits:

                print(
                    f"  {line.asset}: "
                    f"ledger="
                    f"{line.ledger_quantity}, "
                    f"reserve="
                    f"{line.required_reserve}, "
                    f"required="
                    f"{line.required_total}, "
                    f"free="
                    f"{line.exchange_free}, "
                    f"deficit="
                    f"{-line.surplus}"
                )

            print()

            print(
                "No Binance order was sent."
            )

            raise SystemExit(2)

        print(
            "Physical backing   : OK"
        )

        print(
            "Dedicated BNB reserve : "
            f"{dedicated_bnb_fee_reserve} BNB"
        )

        print()

        # =============================================
        # State 6:
        # New + fresh + clean + physically backed.
        # =============================================

        print(
            "Decision           : READY"
        )

        print()

        print(
            "Current monthly portfolio detected "
            "and all runner safety checks "
            "passed."
        )

        # =============================================
        # Safe orchestration test:
        # invoke the real executor WITHOUT its
        # execution flag.
        # =============================================

        if args.preview_if_ready:

            print()
            print(
                "Launching rebalance executor "
                "in DRY-RUN mode..."
            )

            command = [
                sys.executable,
                str(
                    ROOT
                    / "scripts"
                    / "execute_full_rebalance.py"
                ),
            ]

            result = subprocess.run(
                command,
                cwd=str(ROOT),
                check=False,
            )

            print()
            print(
                f"Dry-run exit code  : "
                f"{result.returncode}"
            )

            if result.returncode != 0:
                raise RuntimeError(
                    "Rebalance dry-run returned "
                    "a non-zero exit code."
                )

            print()
            print(
                "WEEKLY PREVIEW: COMPLETE"
            )

            print(
                "No Binance order was sent."
            )

            return
        
        # =============================================
        # Observation-only invocation.
        # =============================================

        if not args.execute_if_ready:

            print()

            print(
                "Execution not requested."
            )

            print(
                "No Binance order was sent."
            )

            return

        # =============================================
        # Automated execution requires THREE things:
        #
        # 1 runner CLI flag
        # 2 automation env switch
        # 3 trading env switch
        # =============================================

        if not automation_enabled:

            raise RuntimeError(
                "AUTOMATION BLOCKED: "
                "ETF_WEEKLY_AUTOMATION_ENABLED="
                "false"
            )

        if not trading_enabled:

            raise RuntimeError(
                "AUTOMATION BLOCKED: "
                "BINANCE_TRADING_ENABLED=false"
            )

        print()
        print(
            "Launching protected full "
            "rebalance executor..."
        )

        command = [
            sys.executable,
            str(
                ROOT
                / "scripts"
                / "execute_full_rebalance.py"
            ),
            "--execute-full-rebalance",
        ]

        result = subprocess.run(
            command,
            cwd=str(ROOT),
            check=False,
        )

        print()

        print(
            f"Executor exit code : "
            f"{result.returncode}"
        )

        if result.returncode != 0:

            raise RuntimeError(
                "Full rebalance executor "
                "returned a non-zero exit code."
            )

        print()

        print(
            "WEEKLY RUNNER: COMPLETE"
        )

    finally:

        release_lock(
            lock_fd
        )


if __name__ == "__main__":
    main()
