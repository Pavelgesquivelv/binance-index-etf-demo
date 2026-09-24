from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


class OrderRepository:

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def reserve_order(
        self,
        conn: sqlite3.Connection,
        *,
        client_order_id: str,
        symbol: str,
        asset: str,
        side: str,
        requested_quantity: Decimal | None,
        requested_quote_quantity: Decimal | None,
        rebalance_run_id: int | None = None,
        contribution_id: int | None = None,
    ) -> int:

        side = side.upper()

        has_rebalance_owner = (
            rebalance_run_id
            is not None
        )

        has_contribution_owner = (
            contribution_id
            is not None
        )

        if (
            has_rebalance_owner
            == has_contribution_owner
        ):
            raise ValueError(
                "Order must belong to exactly "
                "one owner: rebalance_run_id "
                "or contribution_id."
            )

        if side not in {"BUY", "SELL"}:
            raise ValueError(
                f"Unsupported side: {side}"
            )

        if not client_order_id.startswith(
            "IDXETF_"
        ):
            raise ValueError(
                "Invalid ETF clientOrderId."
            )

        cursor = conn.execute(
            """
            INSERT INTO orders (
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
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                rebalance_run_id,
                contribution_id,
                self._utc_now(),
                client_order_id,
                symbol,
                asset,
                side,
                "MARKET",
                (
                    str(requested_quantity)
                    if requested_quantity
                    is not None
                    else None
                ),
                (
                    str(requested_quote_quantity)
                    if requested_quote_quantity
                    is not None
                    else None
                ),
                None,
                "NOT_SENT",
                None,
                None,
                None,
            ),
        )

        order_id = int(
            cursor.lastrowid
        )

        conn.execute(
            """
            INSERT INTO order_lifecycle (
                order_id,
                local_status,
                updated_at_utc,
                last_error
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                order_id,
                "RESERVED",
                self._utc_now(),
                None,
            ),
        )

        return order_id

    def mark_exchange_ack(
        self,
        conn: sqlite3.Connection,
        *,
        order_id: int,
        response: dict[str, Any],
    ) -> None:

        conn.execute(
            """
            UPDATE orders
            SET
                exchange_order_id = ?,
                exchange_status = ?,
                executed_quantity = ?,
                cumulative_quote_quantity = ?,
                response_json = ?
            WHERE id = ?
            """,
            (
                str(
                    response.get(
                        "orderId",
                        "",
                    )
                ),
                str(
                    response.get(
                        "status",
                        "",
                    )
                ),
                str(
                    response.get(
                        "executedQty",
                        "0",
                    )
                ),
                str(
                    response.get(
                        "cummulativeQuoteQty",
                        "0",
                    )
                ),
                json.dumps(
                    response,
                    sort_keys=True,
                ),
                order_id,
            ),
        )

        self._set_status(
            conn,
            order_id=order_id,
            status="EXCHANGE_ACK",
            error=None,
        )

    def mark_submit_unknown(
        self,
        conn: sqlite3.Connection,
        *,
        order_id: int,
        error: str,
    ) -> None:

        self._set_status(
            conn,
            order_id=order_id,
            status="SUBMIT_UNKNOWN",
            error=error,
        )

    def mark_accounted(
        self,
        conn: sqlite3.Connection,
        *,
        order_id: int,
    ) -> None:

        self._set_status(
            conn,
            order_id=order_id,
            status="ACCOUNTED",
            error=None,
        )

    def _set_status(
        self,
        conn: sqlite3.Connection,
        *,
        order_id: int,
        status: str,
        error: str | None,
    ) -> None:

        conn.execute(
            """
            UPDATE order_lifecycle
            SET
                local_status = ?,
                updated_at_utc = ?,
                last_error = ?
            WHERE order_id = ?
            """,
            (
                status,
                self._utc_now(),
                error,
                order_id,
            ),
        )

    def get_recoverable_orders(
        self,
        conn: sqlite3.Connection,
    ) -> list[dict]:

        rows = conn.execute(
            """
            SELECT
                o.id,
                o.rebalance_run_id,
                o.contribution_id,
                o.client_order_id,
                o.symbol,
                o.asset,
                o.side,
                o.requested_quantity,
                o.requested_quote_quantity,
                o.exchange_order_id,
                o.exchange_status,
                l.local_status,
                l.updated_at_utc,
                l.last_error
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE l.local_status
                  != 'ACCOUNTED'
            ORDER BY o.id
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]


    def get_by_client_order_id(
        self,
        conn: sqlite3.Connection,
        client_order_id: str,
    ) -> dict | None:

        row = conn.execute(
            """
            SELECT
                o.*,
                l.local_status,
                l.updated_at_utc,
                l.last_error
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE o.client_order_id = ?
            """,
            (client_order_id,),
        ).fetchone()

        if row is None:
            return None

        return dict(row)
