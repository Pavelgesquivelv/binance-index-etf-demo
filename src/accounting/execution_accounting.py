from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


ZERO = Decimal("0")


@dataclass(frozen=True)
class ExecutionFill:
    trade_id: str | None
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    commission: Decimal
    commission_asset: str


@dataclass(frozen=True)
class ExecutedOrder:
    client_order_id: str
    exchange_order_id: str | None

    symbol: str
    base_asset: str
    quote_asset: str

    side: str
    order_type: str
    status: str

    requested_quantity: Decimal | None
    requested_quote_quantity: Decimal | None

    fills: tuple[ExecutionFill, ...]

    response_payload: dict[str, Any] | None = None

    @property
    def executed_quantity(self) -> Decimal:
        return sum(
            (fill.quantity for fill in self.fills),
            ZERO,
        )

    @property
    def cumulative_quote_quantity(self) -> Decimal:
        return sum(
            (
                fill.quote_quantity
                for fill in self.fills
            ),
            ZERO,
        )


class ExecutionAccounting:

    def __init__(
        self,
        base_currency: str = "USDC",
    ):
        self.base_currency = (
            base_currency.upper()
        )

    @staticmethod
    def _fees_by_asset(
        order: ExecutedOrder,
    ) -> dict[str, Decimal]:

        totals: dict[str, Decimal] = {}

        for fill in order.fills:
            asset = (
                fill.commission_asset
                .upper()
            )

            totals[asset] = (
                totals.get(
                    asset,
                    ZERO,
                )
                + fill.commission
            )

        return totals

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def start_rebalance(
        self,
        conn: sqlite3.Connection,
        *,
        cutoff_utc: str,
        index_level: Decimal,
        nav_before: Decimal,
    ) -> int:

        cursor = conn.execute(
            """
            INSERT INTO rebalance_runs (
                started_at_utc,
                cutoff_utc,
                index_level,
                nav_before_usdc,
                status,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._utc_now(),
                cutoff_utc,
                str(index_level),
                str(nav_before),
                "IN_PROGRESS",
                None,
            ),
        )

        return int(cursor.lastrowid)

    def finish_rebalance(
        self,
        conn: sqlite3.Connection,
        *,
        rebalance_run_id: int,
        status: str,
        notes: str | None = None,
    ) -> None:

        conn.execute(
            """
            UPDATE rebalance_runs
            SET
                completed_at_utc = ?,
                status = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                self._utc_now(),
                status,
                notes,
                rebalance_run_id,
            ),
        )

    def apply_order(
        self,
        conn: sqlite3.Connection,
        *,
        rebalance_run_id: int,
        order: ExecutedOrder,
    ) -> int:

        side = order.side.upper()

        if side not in {
            "BUY",
            "SELL",
        }:
            raise ValueError(
                f"Unsupported side: {side}"
            )

        timestamp = self._utc_now()

        cursor = conn.execute(
            """
            INSERT INTO orders (
                rebalance_run_id,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rebalance_run_id,
                timestamp,
                order.client_order_id,
                order.symbol,
                order.base_asset,
                side,
                order.order_type,
                (
                    str(order.requested_quantity)
                    if order.requested_quantity
                    is not None
                    else None
                ),
                (
                    str(
                        order.requested_quote_quantity
                    )
                    if order.requested_quote_quantity
                    is not None
                    else None
                ),
                order.exchange_order_id,
                order.status,
                str(
                    order.executed_quantity
                ),
                str(
                    order.cumulative_quote_quantity
                ),
                (
                    json.dumps(
                        order.response_payload,
                        sort_keys=True,
                    )
                    if order.response_payload
                    is not None
                    else None
                ),
            ),
        )

        order_id = int(
            cursor.lastrowid
        )

        # ---------------------------------------------
        # Record fills first
        # ---------------------------------------------

        for fill in order.fills:

            conn.execute(
                """
                INSERT INTO fills (
                    order_id,
                    trade_id,
                    price,
                    quantity,
                    quote_quantity,
                    commission,
                    commission_asset
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    fill.trade_id,
                    str(fill.price),
                    str(fill.quantity),
                    str(
                        fill.quote_quantity
                    ),
                    str(fill.commission),
                    fill.commission_asset.upper(),
                ),
            )

            conn.execute(
                """
                INSERT INTO fee_ledger (
                    timestamp_utc,
                    asset,
                    amount,
                    order_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    timestamp,
                    fill.commission_asset.upper(),
                    str(fill.commission),
                    order_id,
                ),
            )

        # ---------------------------------------------
        # Apply trade itself
        # ---------------------------------------------

        executed_quantity = (
            order.executed_quantity
        )

        quote_quantity = (
            order.cumulative_quote_quantity
        )

        fees_by_asset = (
            self._fees_by_asset(order)
        )

        base_asset = (
            order.base_asset.upper()
        )

        base_asset_fee = (
            fees_by_asset.get(
                base_asset,
                ZERO,
            )
        )

        if order.side.upper() == "BUY":

            net_received_quantity = (
                executed_quantity
                - base_asset_fee
            )

            if net_received_quantity <= 0:
                raise RuntimeError(
                    "BUY produced non-positive "
                    "net received quantity."
                )

            self._apply_position_delta(
                conn,
                asset=order.base_asset,
                quantity_delta=(
                    net_received_quantity
                ),
                event_type="TRADE_BUY",
                order_id=order_id,
                buy_cost=quote_quantity,
                notes=order.client_order_id,
            )

            self._apply_cash_delta(
                conn,
                amount=-quote_quantity,
                event_type="TRADE_BUY",
                reference=(
                    order.client_order_id
                ),
            )

        else:

            self._apply_position_delta(
                conn,
                asset=order.base_asset,
                quantity_delta=-executed_quantity,
                event_type="TRADE_SELL",
                order_id=order_id,
                buy_cost=None,
                notes=order.client_order_id,
            )

            self._apply_cash_delta(
                conn,
                amount=quote_quantity,
                event_type="TRADE_SELL",
                reference=order.client_order_id,
            )

        # ---------------------------------------------
        # Apply actual commissions
        # ---------------------------------------------

        for fill in order.fills:

            fee = fill.commission

            if fee <= 0:
                continue

            fee_asset = (
                fill.commission_asset
                .upper()
            )

            if (
                fee_asset
                == self.base_currency
            ):

                self._apply_cash_delta(
                    conn,
                    amount=-fee,
                    event_type="FEE",
                    reference=(
                        order.client_order_id
                    ),
                )

            elif (
                order.side.upper() == "BUY"
                and fee_asset == base_asset
            ):
                # Already deducted from the
                # net received BUY quantity.
                pass

            else:

                self._apply_position_delta(
                    conn,
                    asset=fee_asset,
                    quantity_delta=-fee,
                    event_type="FEE",
                    order_id=order_id,
                    buy_cost=None,
                    notes=(
                        f"Fee for "
                        f"{order.client_order_id}"
                    ),
                )

        return order_id

    def _apply_cash_delta(
        self,
        conn: sqlite3.Connection,
        *,
        amount: Decimal,
        event_type: str,
        reference: str,
    ) -> None:

        conn.execute(
            """
            INSERT INTO cash_ledger (
                timestamp_utc,
                asset,
                amount,
                event_type,
                reference,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._utc_now(),
                self.base_currency,
                str(amount),
                event_type,
                reference,
                None,
            ),
        )

    def _apply_position_delta(
        self,
        conn: sqlite3.Connection,
        *,
        asset: str,
        quantity_delta: Decimal,
        event_type: str,
        order_id: int | None,
        buy_cost: Decimal | None,
        notes: str | None,
    ) -> None:

        asset = asset.upper()

        row = conn.execute(
            """
            SELECT
                quantity,
                average_cost_usdc
            FROM positions
            WHERE asset = ?
            """,
            (asset,),
        ).fetchone()

        if row is None:
            old_quantity = ZERO
            old_average_cost = ZERO
        else:
            old_quantity = Decimal(
                row["quantity"]
            )

            old_average_cost = Decimal(
                row["average_cost_usdc"]
            )

        new_quantity = (
            old_quantity
            + quantity_delta
        )

        if new_quantity < 0:
            raise RuntimeError(
                f"ETF ledger insufficient "
                f"{asset}: "
                f"available={old_quantity}, "
                f"requested_delta={quantity_delta}"
            )

        if quantity_delta > 0:

            if buy_cost is not None:
                previous_cost = (
                    old_quantity
                    * old_average_cost
                )

                new_average_cost = (
                    previous_cost
                    + buy_cost
                ) / new_quantity

            else:
                new_average_cost = (
                    old_average_cost
                )

        else:
            new_average_cost = (
                old_average_cost
                if new_quantity > 0
                else ZERO
            )

        timestamp = self._utc_now()

        conn.execute(
            """
            INSERT INTO position_ledger (
                timestamp_utc,
                asset,
                quantity_delta,
                event_type,
                order_id,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                asset,
                str(quantity_delta),
                event_type,
                order_id,
                notes,
            ),
        )

        conn.execute(
            """
            INSERT INTO positions (
                asset,
                quantity,
                average_cost_usdc,
                updated_at_utc
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(asset)
            DO UPDATE SET
                quantity = excluded.quantity,
                average_cost_usdc =
                    excluded.average_cost_usdc,
                updated_at_utc =
                    excluded.updated_at_utc
            """,
            (
                asset,
                str(new_quantity),
                str(new_average_cost),
                timestamp,
            ),
        )

    def apply_existing_order(
        self,
        conn: sqlite3.Connection,
        *,
        order_id: int,
        order: ExecutedOrder,
    ) -> None:

        row = conn.execute(
            """
            SELECT
                client_order_id,
                symbol,
                asset,
                side
            FROM orders
            WHERE id = ?
            """,
            (order_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Local order not found: "
                f"{order_id}"
            )

        if (
            row["client_order_id"]
            != order.client_order_id
        ):
            raise RuntimeError(
                "clientOrderId mismatch."
            )

        if row["symbol"] != order.symbol:
            raise RuntimeError(
                "Symbol mismatch."
            )

        if (
            row["side"].upper()
            != order.side.upper()
        ):
            raise RuntimeError(
                "Order side mismatch."
            )

        existing_fills = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()["n"]

        if existing_fills:
            raise RuntimeError(
                f"Order {order_id} already "
                f"has accounted fills."
            )

        timestamp = self._utc_now()

        # ---------------------------------------------
        # Record fills and fee ledger
        # ---------------------------------------------

        for fill in order.fills:

            conn.execute(
                """
                INSERT INTO fills (
                    order_id,
                    trade_id,
                    price,
                    quantity,
                    quote_quantity,
                    commission,
                    commission_asset
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    fill.trade_id,
                    str(fill.price),
                    str(fill.quantity),
                    str(fill.quote_quantity),
                    str(fill.commission),
                    fill.commission_asset.upper(),
                ),
            )

            conn.execute(
                """
                INSERT INTO fee_ledger (
                    timestamp_utc,
                    asset,
                    amount,
                    order_id
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    timestamp,
                    fill.commission_asset.upper(),
                    str(fill.commission),
                    order_id,
                ),
            )

        executed_quantity = (
            order.executed_quantity
        )

        quote_quantity = (
            order.cumulative_quote_quantity
        )

        # ---------------------------------------------
        # Apply trade
        # ---------------------------------------------

        if order.side.upper() == "BUY":

            self._apply_position_delta(
                conn,
                asset=order.base_asset,
                quantity_delta=executed_quantity,
                event_type="TRADE_BUY",
                order_id=order_id,
                buy_cost=quote_quantity,
                notes=order.client_order_id,
            )

            self._apply_cash_delta(
                conn,
                amount=-quote_quantity,
                event_type="TRADE_BUY",
                reference=order.client_order_id,
            )

        elif order.side.upper() == "SELL":

            self._apply_position_delta(
                conn,
                asset=order.base_asset,
                quantity_delta=-executed_quantity,
                event_type="TRADE_SELL",
                order_id=order_id,
                buy_cost=None,
                notes=order.client_order_id,
            )

            self._apply_cash_delta(
                conn,
                amount=quote_quantity,
                event_type="TRADE_SELL",
                reference=order.client_order_id,
            )

        else:
            raise ValueError(
                f"Unsupported side: "
                f"{order.side}"
            )

        # ---------------------------------------------
        # Actual Binance commissions
        # ---------------------------------------------

        for fill in order.fills:

            fee = fill.commission

            if fee <= 0:
                continue

            fee_asset = (
                fill.commission_asset
                .upper()
            )

            if (
                fee_asset
                == self.base_currency
            ):

                self._apply_cash_delta(
                    conn,
                    amount=-fee,
                    event_type="FEE",
                    reference=(
                        order.client_order_id
                    ),
                )

            else:

                self._apply_position_delta(
                    conn,
                    asset=fee_asset,
                    quantity_delta=-fee,
                    event_type="FEE",
                    order_id=order_id,
                    buy_cost=None,
                    notes=(
                        f"Fee for "
                        f"{order.client_order_id}"
                    ),
                )