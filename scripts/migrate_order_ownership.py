from __future__ import annotations

import sqlite3
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


with (
    ROOT / "config" / "runtime.yaml"
).open(
    "r",
    encoding="utf-8",
) as file:
    config = yaml.safe_load(file)


db_path = (
    ROOT
    / config["storage"]["database"]
)


conn = sqlite3.connect(
    db_path,
    timeout=30,
)

conn.row_factory = sqlite3.Row


try:

    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(orders)"
        )
    }

    if "contribution_id" in columns:

        print(
            "Order ownership migration: "
            "ALREADY APPLIED"
        )

    else:

        before_orders = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders
            """
        ).fetchone()["n"]

        before_max_id = conn.execute(
            """
            SELECT COALESCE(MAX(id), 0) AS n
            FROM orders
            """
        ).fetchone()["n"]

        print(
            f"Orders before : {before_orders}"
        )

        print(
            f"Max order ID  : {before_max_id}"
        )

        # FK checks must be disabled outside
        # the migration transaction while the
        # parent table is reconstructed.
        conn.execute(
            "PRAGMA foreign_keys = OFF"
        )

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        try:

            conn.execute(
                """
                CREATE TABLE orders_new (
                    id INTEGER
                        PRIMARY KEY AUTOINCREMENT,

                    rebalance_run_id INTEGER,
                    contribution_id INTEGER,

                    created_at_utc TEXT NOT NULL,

                    client_order_id
                        TEXT NOT NULL UNIQUE,

                    symbol TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,

                    requested_quantity TEXT,
                    requested_quote_quantity TEXT,

                    exchange_order_id TEXT,
                    exchange_status TEXT,

                    executed_quantity TEXT,
                    cumulative_quote_quantity TEXT,

                    response_json TEXT,

                    FOREIGN KEY (
                        rebalance_run_id
                    )
                    REFERENCES rebalance_runs(id),

                    FOREIGN KEY (
                        contribution_id
                    )
                    REFERENCES cash_contributions(id),

                    CHECK (
                        (
                            rebalance_run_id
                            IS NOT NULL
                            AND contribution_id
                            IS NULL
                        )
                        OR
                        (
                            rebalance_run_id
                            IS NULL
                            AND contribution_id
                            IS NOT NULL
                        )
                    )
                )
                """
            )

            conn.execute(
                """
                INSERT INTO orders_new (
                    id,
                    rebalance_run_id,
                    contribution_id,
                    created_at_utc,
                    client_order_id,
                    symbol,
                    asset,
                    side,
                    order_type,
                    requested_quantity,
                    requested_quote_quantity,
                    exchange_order_id,
                    exchange_status,
                    executed_quantity,
                    cumulative_quote_quantity,
                    response_json
                )
                SELECT
                    id,
                    rebalance_run_id,
                    NULL,
                    created_at_utc,
                    client_order_id,
                    symbol,
                    asset,
                    side,
                    order_type,
                    requested_quantity,
                    requested_quote_quantity,
                    exchange_order_id,
                    exchange_status,
                    executed_quantity,
                    cumulative_quote_quantity,
                    response_json
                FROM orders
                ORDER BY id
                """
            )

            copied = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM orders_new
                """
            ).fetchone()["n"]

            if copied != before_orders:
                raise RuntimeError(
                    "Order row count changed "
                    "during migration. "
                    f"before={before_orders}, "
                    f"copied={copied}"
                )

            conn.execute(
                "DROP TABLE orders"
            )

            conn.execute(
                """
                ALTER TABLE orders_new
                RENAME TO orders
                """
            )

            # Normalize AUTOINCREMENT sequence
            # after preserving historical IDs.
            max_id = conn.execute(
                """
                SELECT COALESCE(MAX(id), 0)
                FROM orders
                """
            ).fetchone()[0]

            conn.execute(
                """
                DELETE FROM sqlite_sequence
                WHERE name IN (
                    'orders',
                    'orders_new'
                )
                """
            )

            conn.execute(
                """
                INSERT INTO sqlite_sequence (
                    name,
                    seq
                )
                VALUES ('orders', ?)
                """,
                (
                    max_id,
                ),
            )

            conn.commit()

        except Exception:

            conn.rollback()
            raise

        finally:

            conn.execute(
                "PRAGMA foreign_keys = ON"
            )

        after_orders = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders
            """
        ).fetchone()["n"]

        after_max_id = conn.execute(
            """
            SELECT COALESCE(MAX(id), 0) AS n
            FROM orders
            """
        ).fetchone()["n"]

        if after_orders != before_orders:
            raise RuntimeError(
                "Post-migration order count "
                "does not match."
            )

        if after_max_id != before_max_id:
            raise RuntimeError(
                "Historical order IDs changed."
            )

        bad_owner_rows = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders
            WHERE NOT (
                (
                    rebalance_run_id
                    IS NOT NULL
                    AND contribution_id
                    IS NULL
                )
                OR
                (
                    rebalance_run_id
                    IS NULL
                    AND contribution_id
                    IS NOT NULL
                )
            )
            """
        ).fetchone()["n"]

        if bad_owner_rows:
            raise RuntimeError(
                "Invalid order ownership "
                "detected after migration."
            )

        violations = conn.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            raise RuntimeError(
                "Foreign key violations "
                "detected after migration: "
                f"{[dict(x) for x in violations]}"
            )

        print(
            "Order ownership migration: OK"
        )

        print(
            f"Orders after  : {after_orders}"
        )

        print(
            f"Max order ID  : {after_max_id}"
        )

        print(
            "Historical owners: "
            "REBALANCE"
        )

        print(
            "Foreign key check: OK"
        )


finally:

    conn.close()
