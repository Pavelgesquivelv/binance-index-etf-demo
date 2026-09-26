from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_repository import (
    ContributionRepository,
)
from src.contributions.funding_repository import (
    ContributionFundingRepository,
)
from src.storage.database import Database


with (
    ROOT / "config" / "runtime.yaml"
).open(
    "r",
    encoding="utf-8",
) as file:
    config = yaml.safe_load(file)


database = Database(
    str(
        ROOT
        / config["storage"]["database"]
    )
)

contribution_repository = (
    ContributionRepository()
)

funding_repository = (
    ContributionFundingRepository()
)


with database.connection() as conn:

    contribution_repository.ensure_schema(
        conn
    )

    funding_repository.ensure_schema(
        conn
    )

    contribution_columns = conn.execute(
        """
        PRAGMA table_info(
            cash_contributions
        )
        """
    ).fetchall()

    funding_columns = conn.execute(
        """
        PRAGMA table_info(
            contribution_funding_ledger
        )
        """
    ).fetchall()

    funding_rows = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM contribution_funding_ledger
        """
    ).fetchone()["n"]


print(
    "Contribution schema migration: OK"
)

print(
    f"Contribution columns: "
    f"{len(contribution_columns)}"
)

print(
    f"Funding ledger columns: "
    f"{len(funding_columns)}"
)

print(
    f"Funding ledger rows   : "
    f"{funding_rows}"
)

print(
    "Funding initialization: NOT PERFORMED"
)
