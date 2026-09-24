from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import tempfile
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.execution.order_repository import (
    OrderRepository,
)
from src.storage.database import (
    Database,
)


with tempfile.TemporaryDirectory() as td:

    database = Database(
        str(
            Path(td)
            / "ownership_test.db"
        )
    )

    database.initialize_schema()

    repository = OrderRepository()

    with database.connection() as conn:

        rebalance_id = conn.execute(
            """
            INSERT INTO rebalance_runs (
                started_at_utc,
                cutoff_utc,
                index_level,
                nav_before_usdc,
                status,
                notes
            )
            VALUES (
                '2026-09-24T00:00:00+00:00',
                '2026-09-24T00:00:00+00:00',
                '100',
                '5000',
                'IN_PROGRESS',
                NULL
            )
            """
        ).lastrowid

        contribution_id = conn.execute(
            """
            INSERT INTO cash_contributions (
                period_id,
                scheduled_at_utc,
                currency,
                expected_amount,
                feed_cutoff_utc,
                status,
                created_at_utc,
                updated_at_utc
            )
            VALUES (
                '2026-W40',
                '2026-09-28T15:00:00+00:00',
                'USDC',
                '200',
                '2026-09-24T00:00:00+00:00',
                'ACCEPTED_PENDING_INVESTMENT',
                '2026-09-24T00:00:00+00:00',
                '2026-09-24T00:00:00+00:00'
            )
            """
        ).lastrowid

        rebalance_order_id = (
            repository.reserve_order(
                conn,
                rebalance_run_id=(
                    rebalance_id
                ),
                client_order_id=(
                    "IDXETF_R000001_01_BTC"
                ),
                symbol="BTCUSDC",
                asset="BTC",
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    Decimal("20")
                ),
            )
        )

        contribution_order_id = (
            repository.reserve_order(
                conn,
                contribution_id=(
                    contribution_id
                ),
                client_order_id=(
                    "IDXETF_C2026W40_01_BNB"
                ),
                symbol="BNBUSDC",
                asset="BNB",
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    Decimal("20")
                ),
            )
        )

    with database.connection() as conn:

        rebalance_row = conn.execute(
            """
            SELECT
                rebalance_run_id,
                contribution_id
            FROM orders
            WHERE id = ?
            """,
            (
                rebalance_order_id,
            ),
        ).fetchone()

        contribution_row = conn.execute(
            """
            SELECT
                rebalance_run_id,
                contribution_id
            FROM orders
            WHERE id = ?
            """,
            (
                contribution_order_id,
            ),
        ).fetchone()

    assert (
        rebalance_row[
            "rebalance_run_id"
        ]
        == rebalance_id
    )

    assert (
        rebalance_row[
            "contribution_id"
        ]
        is None
    )

    assert (
        contribution_row[
            "rebalance_run_id"
        ]
        is None
    )

    assert (
        contribution_row[
            "contribution_id"
        ]
        == contribution_id
    )

    neither_blocked = False

    try:

        with database.connection() as conn:

            repository.reserve_order(
                conn,
                client_order_id=(
                    "IDXETF_TEST_NEITHER"
                ),
                symbol="BTCUSDC",
                asset="BTC",
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    Decimal("20")
                ),
            )

    except ValueError:
        neither_blocked = True

    assert neither_blocked

    both_blocked = False

    try:

        with database.connection() as conn:

            repository.reserve_order(
                conn,
                rebalance_run_id=(
                    rebalance_id
                ),
                contribution_id=(
                    contribution_id
                ),
                client_order_id=(
                    "IDXETF_TEST_BOTH"
                ),
                symbol="BTCUSDC",
                asset="BTC",
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    Decimal("20")
                ),
            )

    except ValueError:
        both_blocked = True

    assert both_blocked


print(
    "Order ownership test: OK"
)

print(
    "Rebalance-owned order    : OK"
)

print(
    "Contribution-owned order : OK"
)

print(
    "Owner missing            : BLOCKED"
)

print(
    "Dual ownership           : BLOCKED"
)
