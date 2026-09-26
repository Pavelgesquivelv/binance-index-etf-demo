from __future__ import annotations

from contextlib import closing
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
from src.portfolio.owned_reserves import (
    build_owned_minimum_reserves,
    get_contribution_funding_balance,
)
from src.storage.database import Database


with tempfile.TemporaryDirectory() as temp_dir:

    db_path = (
        Path(temp_dir)
        / "owned_reserves_test.db"
    )

    database = Database(
        str(db_path)
    )

    database.initialize_schema()

    funding_repository = (
        ContributionFundingRepository()
    )

    # ---------------------------------------------
    # Empty funding ledger.
    # ---------------------------------------------

    with database.connection() as conn:

        balance = (
            get_contribution_funding_balance(
                conn,
                "USDC",
            )
        )

        assert balance == Decimal("0")

        reserves = (
            build_owned_minimum_reserves(
                conn,
                base_currency="USDC",
                dedicated_bnb_fee_reserve=(
                    Decimal("0.02000000")
                ),
            )
        )

        assert reserves == {
            "BNB": Decimal("0.02000000"),
        }

    # ---------------------------------------------
    # Initialize 2000 USDC funding reserve.
    # ---------------------------------------------

    with database.connection() as conn:

        funding_repository.initialize_funding(
            conn,
            currency="USDC",
            amount=Decimal("2000"),
        )

    with database.connection() as conn:

        reserves = (
            build_owned_minimum_reserves(
                conn,
                base_currency="USDC",
                dedicated_bnb_fee_reserve=(
                    Decimal("0.02000000")
                ),
            )
        )

        assert reserves == {
            "USDC": Decimal("2000"),
            "BNB": Decimal("0.02000000"),
        }

    # ---------------------------------------------
    # Consume one weekly contribution.
    # ---------------------------------------------

    with database.connection() as conn:

        funding_repository.consume_for_contribution(
            conn,
            currency="USDC",
            amount=Decimal("200"),
            period_id="2026-W40",
        )

    with database.connection() as conn:

        reserves = (
            build_owned_minimum_reserves(
                conn,
                base_currency="USDC",
                dedicated_bnb_fee_reserve=(
                    Decimal("0.02000000")
                ),
            )
        )

        assert reserves == {
            "USDC": Decimal("1800"),
            "BNB": Decimal("0.02000000"),
        }

    # ---------------------------------------------
    # Verify helper through a read-only connection.
    #
    # closing() is required here because sqlite3's
    # own context manager commits/rolls back but
    # does not close the file handle on Windows.
    # ---------------------------------------------

    uri = (
        db_path.resolve().as_uri()
        + "?mode=ro"
    )

    with closing(
        sqlite3.connect(
            uri,
            uri=True,
        )
    ) as conn:

        conn.row_factory = sqlite3.Row

        reserves = (
            build_owned_minimum_reserves(
                conn,
                base_currency="USDC",
                dedicated_bnb_fee_reserve=(
                    Decimal("0.02000000")
                ),
            )
        )

        assert reserves == {
            "USDC": Decimal("1800"),
            "BNB": Decimal("0.02000000"),
        }


print(
    "Owned reserves test: OK"
)

print(
    "Initial funding reserve : 2000 USDC"
)

print(
    "After W40 acceptance    : 1800 USDC"
)

print(
    "Dedicated BNB reserve   : 0.02000000 BNB"
)

print(
    "Read-only access        : OK"
)
