from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.funding_repository import (
    ContributionFundingRepository,
)
from src.storage.database import Database


with tempfile.TemporaryDirectory() as temp_dir:

    db_path = (
        Path(temp_dir)
        / "funding_test.db"
    )

    database = Database(
        str(db_path)
    )

    database.initialize_schema()

    repository = (
        ContributionFundingRepository()
    )

    with database.connection() as conn:

        assert (
            repository.get_balance(
                conn,
                "USDC",
            )
            == Decimal("0")
        )

        initial = (
            repository.initialize_funding(
                conn,
                currency="USDC",
                amount=Decimal("2000"),
                notes=(
                    "Test initial weekly "
                    "contribution funding."
                ),
            )
        )

        assert initial == Decimal("2000")

    with database.connection() as conn:

        assert (
            repository.get_balance(
                conn,
                "USDC",
            )
            == Decimal("2000")
        )

        remaining = (
            repository.consume_for_contribution(
                conn,
                currency="USDC",
                amount=Decimal("200"),
                period_id="2026-W40",
            )
        )

        assert remaining == Decimal("1800")

    with database.connection() as conn:

        entries = repository.get_entries(
            conn,
            "USDC",
        )

        assert len(entries) == 2

        assert Decimal(
            entries[0]["amount"]
        ) == Decimal("2000")

        assert Decimal(
            entries[1]["amount"]
        ) == Decimal("-200")

        assert (
            repository.get_balance(
                conn,
                "USDC",
            )
            == Decimal("1800")
        )

    # Duplicate initialization must fail.
    duplicate_initialization_blocked = False

    try:
        with database.connection() as conn:
            repository.initialize_funding(
                conn,
                currency="USDC",
                amount=Decimal("2000"),
            )
    except RuntimeError:
        duplicate_initialization_blocked = True

    assert duplicate_initialization_blocked

    # Duplicate contribution consumption must fail.
    duplicate_period_blocked = False

    try:
        with database.connection() as conn:
            repository.consume_for_contribution(
                conn,
                currency="USDC",
                amount=Decimal("200"),
                period_id="2026-W40",
            )
    except RuntimeError:
        duplicate_period_blocked = True

    assert duplicate_period_blocked

    # Insufficient reserve must fail without mutation.
    insufficient_funding_blocked = False

    try:
        with database.connection() as conn:
            repository.consume_for_contribution(
                conn,
                currency="USDC",
                amount=Decimal("2000"),
                period_id="2026-W41",
            )
    except RuntimeError:
        insufficient_funding_blocked = True

    assert insufficient_funding_blocked

    with database.connection() as conn:

        assert (
            repository.get_balance(
                conn,
                "USDC",
            )
            == Decimal("1800")
        )

    # Direct UPDATE must be impossible.
    update_blocked = False

    try:
        with database.connection() as conn:
            conn.execute(
                """
                UPDATE contribution_funding_ledger
                SET amount = '9999'
                WHERE id = 1
                """
            )
    except sqlite3.IntegrityError:
        update_blocked = True

    assert update_blocked

    # Direct DELETE must be impossible.
    delete_blocked = False

    try:
        with database.connection() as conn:
            conn.execute(
                """
                DELETE FROM
                    contribution_funding_ledger
                WHERE id = 1
                """
            )
    except sqlite3.IntegrityError:
        delete_blocked = True

    assert delete_blocked

    # Transaction rollback must restore funding.
    rollback_ok = False

    try:
        with database.connection() as conn:

            repository.consume_for_contribution(
                conn,
                currency="USDC",
                amount=Decimal("100"),
                period_id="2026-W41",
            )

            raise RuntimeError(
                "Intentional rollback test."
            )

    except RuntimeError as exc:

        if (
            str(exc)
            == "Intentional rollback test."
        ):
            rollback_ok = True
        else:
            raise

    assert rollback_ok

    with database.connection() as conn:

        final_balance = (
            repository.get_balance(
                conn,
                "USDC",
            )
        )

        final_entries = (
            repository.get_entries(
                conn,
                "USDC",
            )
        )

        assert (
            final_balance
            == Decimal("1800")
        )

        assert len(final_entries) == 2


print(
    "Contribution funding ledger test: OK"
)

print(
    "Initial funding       : 2000 USDC"
)

print(
    "Consumed contribution : 200 USDC"
)

print(
    "Remaining funding     : 1800 USDC"
)

print(
    "Duplicate protection  : OK"
)

print(
    "Insufficient funding  : BLOCKED"
)

print(
    "Append-only triggers  : OK"
)

print(
    "Transaction rollback  : OK"
)
