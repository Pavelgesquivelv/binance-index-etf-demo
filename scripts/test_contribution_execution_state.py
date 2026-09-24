from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import tempfile
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_repository import (
    ContributionRepository,
    STATUS_ACCEPTED,
    STATUS_COMPLETED,
    STATUS_INVESTING,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.storage.database import Database


with tempfile.TemporaryDirectory() as td:

    database = Database(
        str(
            Path(td)
            / "contribution_execution.db"
        )
    )

    database.initialize_schema()

    contribution_repository = (
        ContributionRepository()
    )

    order_repository = (
        OrderRepository()
    )

    with database.connection() as conn:

        contribution_repository.ensure_schema(
            conn
        )

        contribution_id = conn.execute(
            """
            INSERT INTO cash_contributions (
                period_id,
                scheduled_at_utc,
                currency,
                expected_amount,
                detected_amount,
                accepted_amount,
                feed_cutoff_utc,
                status,
                created_at_utc,
                updated_at_utc,
                accepted_at_utc
            )
            VALUES (
                '2026-W40',
                '2026-09-28T15:00:00+00:00',
                'USDC',
                '200',
                '200',
                '200',
                '2026-08-31T13:00:00+00:00',
                ?,
                '2026-09-28T15:00:00+00:00',
                '2026-09-28T15:00:00+00:00',
                '2026-09-28T15:00:00+00:00'
            )
            """,
            (
                STATUS_ACCEPTED,
            ),
        ).lastrowid

        contribution_repository\
            .mark_investment_in_progress(
                conn,
                contribution_id=(
                    contribution_id
                ),
            )

        order_id = (
            order_repository.reserve_order(
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

        contribution = conn.execute(
            """
            SELECT status
            FROM cash_contributions
            WHERE id = ?
            """,
            (
                contribution_id,
            ),
        ).fetchone()

        assert (
            contribution["status"]
            == STATUS_INVESTING
        )

        order = (
            order_repository
            .get_by_client_order_id(
                conn,
                "IDXETF_C2026W40_01_BNB",
            )
        )

        assert order is not None

        assert (
            order["contribution_id"]
            == contribution_id
        )

        assert (
            order["rebalance_run_id"]
            is None
        )

        assert (
            order["local_status"]
            == "RESERVED"
        )

        order_repository.mark_exchange_ack(
            conn,
            order_id=order_id,
            response={
                "orderId": 123456789,
                "status": "FILLED",
                "executedQty": "0.025",
                "cummulativeQuoteQty": "20",
            },
        )

        order_repository.mark_accounted(
            conn,
            order_id=order_id,
        )

        contribution_repository\
            .mark_completed(
                conn,
                contribution_id=(
                    contribution_id
                ),
                notes=(
                    "Test investment complete."
                ),
            )

    with database.connection() as conn:

        contribution = conn.execute(
            """
            SELECT status
            FROM cash_contributions
            WHERE id = ?
            """,
            (
                contribution_id,
            ),
        ).fetchone()

        assert (
            contribution["status"]
            == STATUS_COMPLETED
        )

        order = (
            order_repository
            .get_by_client_order_id(
                conn,
                "IDXETF_C2026W40_01_BNB",
            )
        )

        assert (
            order["local_status"]
            == "ACCOUNTED"
        )


print(
    "Contribution execution state test: OK"
)

print(
    "ACCEPTED -> IN_PROGRESS : OK"
)

print(
    "Contribution ownership  : OK"
)

print(
    "RESERVED -> ACCOUNTED    : OK"
)

print(
    "IN_PROGRESS -> COMPLETED : OK"
)
