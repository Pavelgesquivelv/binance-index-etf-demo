from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.storage.database import Database


def main():
    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    database_path = (
        ROOT
        / config["storage"]["database"]
    )

    database = Database(
        str(database_path)
    )

    database.initialize_schema()

    print(
        f"Database migrated: {database_path}"
    )

    print()
    print("Tables")
    print("-" * 60)

    with database.connection() as conn:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        ).fetchall()

    for row in rows:
        print(row["name"])


if __name__ == "__main__":
    main()
