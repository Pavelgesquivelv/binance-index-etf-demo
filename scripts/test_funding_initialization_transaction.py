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
from src.storage.database import (
    Database,
)


ZERO = Decimal("0")
AMOUNT = Decimal("2000")
CURRENCY = "USDC"


class IntentionalRollback(Exception):
    pass


def accounting_snapshot(
    database: Database,
) -> dict:

    with database.connection() as conn:

        return {
            "cash_ledger": tuple(
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM cash_ledger
                    ORDER BY id
                    """
                ).fetchall()
            ),
            "positions": tuple(
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM positions
                    ORDER BY asset
                    """
                ).fetchall()
            ),
            "nav_snapshots": tuple(
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM nav_snapshots
                    ORDER BY id
                    """
                ).fetchall()
            ),
            "cash_contributions": tuple(
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM cash_contributions
                    ORDER BY id
                    """
                ).fetchall()
            ),
            "orders": tuple(
                tuple(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM orders
                    ORDER BY id
                    """
                ).fetchall()
            ),
        }


with tempfile.TemporaryDirectory() as tmp:

    db_path = (
        Path(tmp)
        / "funding_initialization.db"
    )

    database = Database(
        str(db_path)
    )

    database.initialize_schema()

    repository = (
        ContributionFundingRepository()
    )

    # --------------------------------------------------
    # Schema/triggers are installed explicitly before
    # operational transactions.
    # --------------------------------------------------

    with database.connection() as conn:

        repository.ensure_schema(
            conn
        )

        conn.execute(
            """
            INSERT OR REPLACE INTO meta (
                key,
                value
            )
            VALUES (?, ?)
            """,
            (
                "shares_outstanding",
                "50",
            ),
        )

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
                "2.58529750",
                "TEST_SEED",
                "TEST_SEED_CASH",
                "Test-only seed.",
            ),
        )

        conn.execute(
            """
            INSERT INTO positions (
                asset,
                quantity,
                average_cost_usdc,
                updated_at_utc
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "BNB",
                "0.63841614",
                "789.81",
                "2026-09-26T00:00:00+00:00",
            ),
        )

    # --------------------------------------------------
    # 1. Initial state.
    # --------------------------------------------------

    before = accounting_snapshot(
        database
    )

    with database.connection() as conn:

        assert (
            repository.get_balance(
                conn,
                CURRENCY,
            )
            == ZERO
        )

        assert len(
            repository.get_entries(
                conn,
                CURRENCY,
            )
        ) == 0

    # --------------------------------------------------
    # 2. Initialization must participate in caller's
    #    transaction and rollback completely.
    # --------------------------------------------------

    try:

        with database.connection() as conn:

            repository.initialize_funding(
                conn,
                currency=CURRENCY,
                amount=AMOUNT,
                notes=(
                    "Intentional rollback test."
                ),
            )

            assert (
                repository.get_balance(
                    conn,
                    CURRENCY,
                )
                == AMOUNT
            )

            raise IntentionalRollback()

    except IntentionalRollback:
        pass

    with database.connection() as conn:

        assert (
            repository.get_balance(
                conn,
                CURRENCY,
            )
            == ZERO
        )

        assert len(
            repository.get_entries(
                conn,
                CURRENCY,
            )
        ) == 0

    assert (
        accounting_snapshot(database)
        == before
    )

    # --------------------------------------------------
    # 3. Successful initialization changes only the
    #    funding ledger.
    # --------------------------------------------------

    with database.connection() as conn:

        repository.initialize_funding(
            conn,
            currency=CURRENCY,
            amount=AMOUNT,
            notes=(
                "Successful initialization test."
            ),
        )

    after = accounting_snapshot(
        database
    )

    assert after == before

    with database.connection() as conn:

        balance = (
            repository.get_balance(
                conn,
                CURRENCY,
            )
        )

        entries = (
            repository.get_entries(
                conn,
                CURRENCY,
            )
        )

    assert balance == AMOUNT
    assert len(entries) == 1

    assert (
        entries[0]["reference"]
        == "INITIAL_FUNDING:USDC"
    )

    assert (
        Decimal(entries[0]["amount"])
        == AMOUNT
    )

    # --------------------------------------------------
    # 4. Duplicate initialization must fail and leave
    #    the original reserve untouched.
    # --------------------------------------------------

    duplicate_blocked = False

    try:

        with database.connection() as conn:

            repository.initialize_funding(
                conn,
                currency=CURRENCY,
                amount=AMOUNT,
                notes="Duplicate attempt.",
            )

    except RuntimeError:
        duplicate_blocked = True

    assert duplicate_blocked

    with database.connection() as conn:

        final_balance = (
            repository.get_balance(
                conn,
                CURRENCY,
            )
        )

        final_entries = (
            repository.get_entries(
                conn,
                CURRENCY,
            )
        )

    assert final_balance == AMOUNT
    assert len(final_entries) == 1


print(
    "Funding initialization transaction test: OK"
)

print(
    "Rollback before commit        : OK"
)

print(
    "Successful funding balance    : 2000 USDC"
)

print(
    "ETF accounting unchanged      : OK"
)

print(
    "Duplicate initialization      : BLOCKED"
)

print(
    "Funding ledger rows           : 1"
)
