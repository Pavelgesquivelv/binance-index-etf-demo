from __future__ import annotations

from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_repository import (
    ContributionRepository,
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

repository = ContributionRepository()

with database.connection() as conn:

    repository.ensure_schema(conn)

    columns = conn.execute(
        """
        PRAGMA table_info(
            cash_contributions
        )
        """
    ).fetchall()


print(
    "Contribution schema migration: OK"
)

print(
    f"Columns: {len(columns)}"
)

for row in columns:
    print(
        f"  {row['name']}"
    )
