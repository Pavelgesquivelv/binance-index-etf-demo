from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


with (
    ROOT
    / "config"
    / "runtime.yaml"
).open(
    "r",
    encoding="utf-8",
) as file:

    config = yaml.safe_load(file)


database_path = (
    ROOT
    / config["storage"]["database"]
)


conn = sqlite3.connect(
    database_path,
    timeout=30,
)


try:

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS
            valuation_snapshots (

            id INTEGER
                PRIMARY KEY AUTOINCREMENT,

            bucket_utc TEXT
                NOT NULL UNIQUE,

            captured_at_utc TEXT
                NOT NULL,

            cash_usdc TEXT
                NOT NULL,

            market_value_usdc TEXT
                NOT NULL,

            nav_usdc TEXT
                NOT NULL,

            shares_outstanding TEXT
                NOT NULL,

            nav_per_share_usdc TEXT
                NOT NULL,

            index_level TEXT,

            feed_cutoff_utc TEXT
                NOT NULL,

            valuation_source TEXT
                NOT NULL
        );

        CREATE INDEX IF NOT EXISTS
            ix_valuation_snapshots_captured_at
        ON valuation_snapshots(
            captured_at_utc
        );
        """
    )

    conn.commit()

    violations = conn.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    if violations:
        raise RuntimeError(
            "Foreign key violations: "
            f"{violations}"
        )

    print(
        "valuation_snapshots migration: OK"
    )

    print(
        "Rows:",
        conn.execute(
            """
            SELECT COUNT(*)
            FROM valuation_snapshots
            """
        ).fetchone()[0],
    )

finally:

    conn.close()
