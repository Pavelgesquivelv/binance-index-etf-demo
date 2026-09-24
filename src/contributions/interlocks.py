from __future__ import annotations

import sqlite3


BLOCKING_CONTRIBUTION_STATUSES = (
    "ACCEPTED_PENDING_INVESTMENT",
    "INVESTMENT_IN_PROGRESS",
    "RECOVERY_REQUIRED",
)


def get_blocking_contributions(
    conn: sqlite3.Connection,
) -> list[dict]:

    table_exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'cash_contributions'
        """
    ).fetchone()

    if table_exists is None:
        return []

    placeholders = ", ".join(
        "?"
        for _ in BLOCKING_CONTRIBUTION_STATUSES
    )

    rows = conn.execute(
        f"""
        SELECT
            id,
            period_id,
            status,
            accepted_amount,
            feed_cutoff_utc,
            updated_at_utc
        FROM cash_contributions
        WHERE status IN ({placeholders})
        ORDER BY id
        """,
        BLOCKING_CONTRIBUTION_STATUSES,
    ).fetchall()

    return [
        dict(row)
        for row in rows
    ]
