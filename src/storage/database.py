from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, path: str):
        self.path = Path(path)

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            timeout=30,
        )

        conn.row_factory = sqlite3.Row

        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")

        return conn

    @contextmanager
    def connection(
        self,
    ) -> Iterator[sqlite3.Connection]:
        """
        Managed SQLite connection.

        - Commit on success
        - Rollback on exception
        - Always close
        """

        conn = self.connect()

        try:
            yield conn
            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            conn.close()

    def initialize_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cash_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    reference TEXT,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS positions (
                    asset TEXT PRIMARY KEY,
                    quantity TEXT NOT NULL,
                    average_cost_usdc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nav_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    cash_usdc TEXT NOT NULL,
                    market_value_usdc TEXT NOT NULL,
                    nav_usdc TEXT NOT NULL,
                    shares_outstanding TEXT NOT NULL,
                    nav_per_share_usdc TEXT NOT NULL,
                    index_level TEXT,
                    tracking_difference TEXT
                );

                CREATE TABLE IF NOT EXISTS rebalance_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at_utc TEXT NOT NULL,
                    completed_at_utc TEXT,
                    cutoff_utc TEXT NOT NULL,
                    index_level TEXT NOT NULL,
                    nav_before_usdc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    notes TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS
                    ux_rebalance_runs_completed_cutoff
                    ON rebalance_runs(cutoff_utc)
                    WHERE status = 'COMPLETED';

                CREATE TABLE IF NOT EXISTS cash_contributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    period_id TEXT NOT NULL UNIQUE,

                    scheduled_at_utc TEXT NOT NULL,
                    currency TEXT NOT NULL,

                    expected_amount TEXT NOT NULL,
                    detected_amount TEXT,
                    accepted_amount TEXT,

                    feed_cutoff_utc TEXT NOT NULL,

                    nav_before_usdc TEXT,
                    nav_per_share_before_usdc TEXT,

                    shares_before TEXT,
                    shares_issued TEXT,
                    shares_after TEXT,

                    status TEXT NOT NULL,

                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,

                    accepted_at_utc TEXT,
                    completed_at_utc TEXT,

                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    rebalance_run_id INTEGER,
                    contribution_id INTEGER,

                    created_at_utc TEXT NOT NULL,
                    client_order_id TEXT NOT NULL UNIQUE,

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
                    ) REFERENCES rebalance_runs(id),

                    FOREIGN KEY (
                        contribution_id
                    ) REFERENCES cash_contributions(id),

                    CHECK (
                        (
                            rebalance_run_id IS NOT NULL
                            AND contribution_id IS NULL
                        )
                        OR
                        (
                            rebalance_run_id IS NULL
                            AND contribution_id IS NOT NULL
                        )
                    )
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    trade_id TEXT,

                    price TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    quote_quantity TEXT NOT NULL,

                    commission TEXT NOT NULL,
                    commission_asset TEXT NOT NULL,

                    FOREIGN KEY (
                        order_id
                    ) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS position_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,

                    asset TEXT NOT NULL,
                    quantity_delta TEXT NOT NULL,

                    event_type TEXT NOT NULL,

                    order_id INTEGER,
                    notes TEXT,

                    FOREIGN KEY (
                        order_id
                    ) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS fee_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,

                    asset TEXT NOT NULL,
                    amount TEXT NOT NULL,

                    order_id INTEGER NOT NULL,

                    FOREIGN KEY (
                        order_id
                    ) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS order_lifecycle (
                    order_id INTEGER PRIMARY KEY,
                    local_status TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    last_error TEXT,

                    FOREIGN KEY (
                        order_id
                    ) REFERENCES orders(id)
                );

                CREATE TABLE IF NOT EXISTS execution_benchmarks (
                    order_id INTEGER PRIMARY KEY,

                    captured_at_utc TEXT NOT NULL,

                    bid_price TEXT NOT NULL,
                    ask_price TEXT NOT NULL,
                    mid_price TEXT NOT NULL,

                    spread_abs TEXT NOT NULL,
                    spread_bps TEXT NOT NULL,

                    bnb_mid_usdc TEXT,

                    FOREIGN KEY (
                    order_id
                    ) REFERENCES orders(id)
                );
                """
            )