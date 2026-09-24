from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_repository import (
    ContributionRepository,
    STATUS_ACCEPTED,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.storage.database import (
    Database,
)


with tempfile.TemporaryDirectory() as td:

    db_path = (
        Path(td)
        / "contribution_test.db"
    )

    database = Database(
        str(db_path)
    )

    database.initialize_schema()

    ledger = PortfolioLedger(
        database
    )

    created = ledger.initialize_fund(
        fund_name="Contribution Test ETF",
        base_currency="USDC",
        initial_capital=Decimal("5000"),
        shares_outstanding=Decimal("50"),
        order_prefix="IDXETF_",
    )

    assert created

    repository = ContributionRepository()

    with database.connection() as conn:

        repository.ensure_schema(conn)

        result = (
            repository.accept_contribution(
                conn,
                period_id="2026-W40",
                scheduled_at_utc=(
                    "2026-09-28T15:00:00+00:00"
                ),
                currency="USDC",
                amount=Decimal("200"),
                detected_amount=Decimal("200"),
                feed_cutoff_utc=(
                    "2026-08-31T13:00:00+00:00"
                ),
                cash_before=Decimal("5000"),
                market_value_before=Decimal("0"),
                nav_before=Decimal("5000"),
                nav_per_share_before=Decimal("100"),
                shares_before=Decimal("50"),
                index_level=Decimal(
                    "56.4141587009571528399"
                ),
            )
        )

    assert (
        result["shares_issued"]
        == Decimal("2")
    )

    assert (
        result["shares_after"]
        == Decimal("52")
    )

    assert (
        result["nav_after"]
        == Decimal("5200")
    )

    assert (
        result["nav_per_share_after"]
        == Decimal("100")
    )

    assert (
        ledger.get_cash_balance("USDC")
        == Decimal("5200")
    )

    assert (
        Decimal(
            ledger.get_meta(
                "shares_outstanding"
            )
        )
        == Decimal("52")
    )

    latest_nav = (
        ledger.get_latest_nav()
    )

    assert (
        Decimal(
            latest_nav[
                "nav_usdc"
            ]
        )
        == Decimal("5200")
    )

    assert (
        Decimal(
            latest_nav[
                "nav_per_share_usdc"
            ]
        )
        == Decimal("100")
    )

    # ---------------------------------------------
    # Verify lifecycle row.
    # ---------------------------------------------

    with database.connection() as conn:

        row = repository.get_by_period(
            conn,
            "2026-W40",
        )

        assert row is not None

        assert (
            row["status"]
            == STATUS_ACCEPTED
        )

        assert (
            Decimal(
                row["shares_issued"]
            )
            == Decimal("2")
        )

    # ---------------------------------------------
    # Exact same period must NOT be accepted twice.
    # ---------------------------------------------

    duplicate_blocked = False

    try:

        with database.connection() as conn:

            repository.accept_contribution(
                conn,
                period_id="2026-W40",
                scheduled_at_utc=(
                    "2026-09-28T15:00:00+00:00"
                ),
                currency="USDC",
                amount=Decimal("200"),
                detected_amount=Decimal("200"),
                feed_cutoff_utc=(
                    "2026-08-31T13:00:00+00:00"
                ),
                cash_before=Decimal("5200"),
                market_value_before=Decimal("0"),
                nav_before=Decimal("5200"),
                nav_per_share_before=Decimal("100"),
                shares_before=Decimal("52"),
                index_level=Decimal(
                    "56.4141587009571528399"
                ),
            )

    except RuntimeError:
        duplicate_blocked = True

    assert duplicate_blocked

    # Cash and shares must remain unchanged.
    assert (
        ledger.get_cash_balance("USDC")
        == Decimal("5200")
    )

    assert (
        Decimal(
            ledger.get_meta(
                "shares_outstanding"
            )
        )
        == Decimal("52")
    )

    with database.connection() as conn:

        cash_events = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM cash_ledger
            WHERE event_type =
                  'CAPITAL_CONTRIBUTION'
            """
        ).fetchone()["n"]

        # Initial fund + weekly contribution.
        assert cash_events == 2

        contribution_rows = (
            conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM cash_contributions
                """
            ).fetchone()["n"]
        )

        assert contribution_rows == 1


print(
    "Contribution repository test: OK"
)

print(
    "Atomic cash contribution      : OK"
)

print(
    "Share issuance                : OK"
)

print(
    "NAV/share preservation        : OK"
)

print(
    "Weekly period idempotency     : OK"
)

print(
    "Duplicate cash/share mutation : BLOCKED"
)
