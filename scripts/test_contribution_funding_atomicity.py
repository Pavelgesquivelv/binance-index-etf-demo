from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.funding_repository import (
    ContributionFundingRepository,
)
from src.storage.database import Database


class IntentionalRollback(Exception):
    pass


with tempfile.TemporaryDirectory() as temp_dir:

    database = Database(
        str(
            Path(temp_dir)
            / "funding_atomicity.db"
        )
    )

    database.initialize_schema()

    repository = (
        ContributionFundingRepository()
    )

    # ---------------------------------------------
    # Establish committed funding ownership.
    # ---------------------------------------------

    with database.connection() as conn:

        repository.initialize_funding(
            conn,
            currency="USDC",
            amount=Decimal("2000"),
        )

    # ---------------------------------------------
    # Simulate future contribution acceptance.
    #
    # A write made BEFORE funding consumption
    # must also roll back if anything later fails.
    # ---------------------------------------------

    try:

        with database.connection() as conn:

            conn.execute(
                """
                INSERT INTO cash_ledger (
                    timestamp_utc,
                    asset,
                    amount,
                    event_type,
                    reference,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "2026-09-26T00:00:00+00:00",
                    "USDC",
                    "200",
                    "ATOMICITY_TEST",
                    "ATOMICITY_TEST",
                    "must roll back",
                ),
            )

            repository.consume_for_contribution(
                conn,
                currency="USDC",
                amount=Decimal("200"),
                period_id="2026-W40",
            )

            raise IntentionalRollback()

    except IntentionalRollback:
        pass

    # ---------------------------------------------
    # Neither side may survive the rollback.
    # ---------------------------------------------

    with database.connection() as conn:

        funding_balance = (
            repository.get_balance(
                conn,
                "USDC",
            )
        )

        marker = conn.execute(
            """
            SELECT COUNT(*)
            FROM cash_ledger
            WHERE reference = ?
            """,
            ("ATOMICITY_TEST",),
        ).fetchone()[0]

        funding_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM contribution_funding_ledger
            WHERE reference = ?
            """,
            (
                "CONTRIBUTION:"
                "2026-W40:USDC",
            ),
        ).fetchone()[0]

    assert (
        funding_balance
        == Decimal("2000")
    )

    assert marker == 0

    assert funding_rows == 0


print(
    "Contribution funding atomicity test: OK"
)

print(
    "Funding after rollback : 2000 USDC"
)

print(
    "Cash ledger rollback   : OK"
)

print(
    "Funding debit rollback : OK"
)

print(
    "Implicit commit risk   : BLOCKED"
)
