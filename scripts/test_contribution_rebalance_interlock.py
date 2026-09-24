from __future__ import annotations

from pathlib import Path
import tempfile
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.interlocks import (
    get_blocking_contributions,
)
from src.storage.database import Database


with tempfile.TemporaryDirectory() as td:

    database = Database(
        str(
            Path(td)
            / "interlock_test.db"
        )
    )

    database.initialize_schema()

    with database.connection() as conn:

        def create_contribution(
            *,
            period_id: str,
            status: str,
        ) -> int:

            return int(
                conn.execute(
                    """
                    INSERT INTO cash_contributions (
                        period_id,
                        scheduled_at_utc,
                        currency,
                        expected_amount,
                        detected_amount,
                        accepted_amount,
                        feed_cutoff_utc,
                        status,
                        created_at_utc,
                        updated_at_utc
                    )
                    VALUES (
                        ?,
                        '2026-09-28T15:00:00+00:00',
                        'USDC',
                        '200',
                        '200',
                        '200',
                        '2026-08-31T13:00:00+00:00',
                        ?,
                        '2026-09-28T15:00:00+00:00',
                        '2026-09-28T15:00:00+00:00'
                    )
                    """,
                    (
                        period_id,
                        status,
                    ),
                ).lastrowid
            )

        # Waiting for physical funds has not yet
        # changed ETF ownership, therefore it must
        # NOT block an index rebalance.
        pending_id = create_contribution(
            period_id="2026-W39",
            status="PENDING_PHYSICAL_FUNDS",
        )

        assert (
            get_blocking_contributions(
                conn
            )
            == []
        )

        conn.execute(
            """
            DELETE FROM cash_contributions
            WHERE id = ?
            """,
            (pending_id,),
        )

        accepted_id = create_contribution(
            period_id="2026-W40",
            status=(
                "ACCEPTED_PENDING_INVESTMENT"
            ),
        )

        rows = (
            get_blocking_contributions(
                conn
            )
        )

        assert len(rows) == 1
        assert (
            rows[0]["period_id"]
            == "2026-W40"
        )

        conn.execute(
            """
            UPDATE cash_contributions
            SET status =
                'INVESTMENT_IN_PROGRESS'
            WHERE id = ?
            """,
            (accepted_id,),
        )

        rows = (
            get_blocking_contributions(
                conn
            )
        )

        assert len(rows) == 1
        assert (
            rows[0]["status"]
            == "INVESTMENT_IN_PROGRESS"
        )

        conn.execute(
            """
            UPDATE cash_contributions
            SET status =
                'RECOVERY_REQUIRED'
            WHERE id = ?
            """,
            (accepted_id,),
        )

        rows = (
            get_blocking_contributions(
                conn
            )
        )

        assert len(rows) == 1
        assert (
            rows[0]["status"]
            == "RECOVERY_REQUIRED"
        )

        conn.execute(
            """
            UPDATE cash_contributions
            SET status = 'COMPLETED'
            WHERE id = ?
            """,
            (accepted_id,),
        )

        assert (
            get_blocking_contributions(
                conn
            )
            == []
        )


print(
    "Contribution/rebalance interlock test: OK"
)

print(
    "PENDING_PHYSICAL_FUNDS   : does not block"
)

print(
    "ACCEPTED_PENDING_INVESTMENT : BLOCKS"
)

print(
    "INVESTMENT_IN_PROGRESS      : BLOCKS"
)

print(
    "RECOVERY_REQUIRED           : BLOCKS"
)

print(
    "COMPLETED                   : does not block"
)
