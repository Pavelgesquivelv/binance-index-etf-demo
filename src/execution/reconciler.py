from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.accounting.execution_accounting import (
    ExecutedOrder,
    ExecutionAccounting,
    ExecutionFill,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.storage.database import Database


TERMINAL_STATUSES = {
    "FILLED",
    "CANCELED",
    "EXPIRED",
    "EXPIRED_IN_MATCH",
    "REJECTED",
}


@dataclass(frozen=True)
class ReconcileResult:
    order_id: int
    client_order_id: str
    result: str
    exchange_status: str | None
    fills: int
    message: str


class OrderReconciler:

    def __init__(
        self,
        *,
        database: Database,
        client: BinanceDemoClient,
        base_currency: str,
    ):
        self.database = database
        self.client = client

        self.repository = (
            OrderRepository()
        )

        self.accounting = (
            ExecutionAccounting(
                base_currency=base_currency
            )
        )

        self.base_currency = (
            base_currency.upper()
        )

    def reconcile_order(
        self,
        local_order: dict,
    ) -> ReconcileResult:

        order_id = int(
            local_order["id"]
        )

        symbol = local_order["symbol"]

        client_order_id = (
            local_order[
                "client_order_id"
            ]
        )

        # ---------------------------------------------
        # Ask Binance whether this order exists.
        # GET is safe; no trading action occurs.
        # ---------------------------------------------

        exchange_order = (
            self.client
            .get_order_if_exists(
                symbol=symbol,
                client_order_id=(
                    client_order_id
                ),
            )
        )

        if exchange_order is None:

            return ReconcileResult(
                order_id=order_id,
                client_order_id=(
                    client_order_id
                ),
                result="NOT_FOUND",
                exchange_status=None,
                fills=0,
                message=(
                    "Binance does not currently "
                    "know this clientOrderId."
                ),
            )

        exchange_status = str(
            exchange_order["status"]
        )

        # ---------------------------------------------
        # Persist exchange acknowledgement.
        # ---------------------------------------------

        with self.database.connection() as conn:

            self.repository.mark_exchange_ack(
                conn,
                order_id=order_id,
                response=exchange_order,
            )

        # ---------------------------------------------
        # Non-terminal order:
        # do not account it yet.
        # ---------------------------------------------

        if (
            exchange_status
            not in TERMINAL_STATUSES
        ):

            return ReconcileResult(
                order_id=order_id,
                client_order_id=(
                    client_order_id
                ),
                result="PENDING",
                exchange_status=(
                    exchange_status
                ),
                fills=0,
                message=(
                    "Exchange order is not "
                    "terminal yet."
                ),
            )

        executed_qty = Decimal(
            str(
                exchange_order.get(
                    "executedQty",
                    "0",
                )
            )
        )

        # ---------------------------------------------
        # Terminal order with zero execution.
        # Nothing monetary to account.
        # ---------------------------------------------

        if executed_qty == 0:

            with self.database.connection() as conn:

                self.repository.mark_accounted(
                    conn,
                    order_id=order_id,
                )

            return ReconcileResult(
                order_id=order_id,
                client_order_id=(
                    client_order_id
                ),
                result="ACCOUNTED_NO_FILL",
                exchange_status=(
                    exchange_status
                ),
                fills=0,
                message=(
                    "Terminal order had "
                    "zero executed quantity."
                ),
            )

        # ---------------------------------------------
        # Recover actual Binance trades/fills.
        # ---------------------------------------------

        exchange_order_id = int(
            exchange_order["orderId"]
        )

        trades = self.client.get_my_trades(
            symbol=symbol,
            order_id=exchange_order_id,
        )

        if not trades:

            return ReconcileResult(
                order_id=order_id,
                client_order_id=(
                    client_order_id
                ),
                result="WAITING_FOR_TRADES",
                exchange_status=(
                    exchange_status
                ),
                fills=0,
                message=(
                    "Order reports execution, "
                    "but myTrades returned "
                    "no fills yet."
                ),
            )

        fills = tuple(
            ExecutionFill(
                trade_id=(
                    str(
                        trade.get(
                            "id",
                            trade.get(
                                "tradeId",
                                "",
                            ),
                        )
                    )
                    or None
                ),
                price=Decimal(
                    str(trade["price"])
                ),
                quantity=Decimal(
                    str(trade["qty"])
                ),
                quote_quantity=Decimal(
                    str(trade["quoteQty"])
                ),
                commission=Decimal(
                    str(
                        trade[
                            "commission"
                        ]
                    )
                ),
                commission_asset=str(
                    trade[
                        "commissionAsset"
                    ]
                ).upper(),
            )
            for trade in trades
        )

        executed_order = ExecutedOrder(
            client_order_id=(
                client_order_id
            ),
            exchange_order_id=str(
                exchange_order_id
            ),
            symbol=symbol,
            base_asset=(
                local_order["asset"]
            ),
            quote_asset=(
                self.base_currency
            ),
            side=local_order["side"],
            order_type="MARKET",
            status=exchange_status,
            requested_quantity=(
                Decimal(
                    local_order[
                        "requested_quantity"
                    ]
                )
                if local_order[
                    "requested_quantity"
                ]
                is not None
                else None
            ),
            requested_quote_quantity=(
                Decimal(
                    local_order[
                        "requested_quote_quantity"
                    ]
                )
                if local_order[
                    "requested_quote_quantity"
                ]
                is not None
                else None
            ),
            fills=fills,
            response_payload=(
                exchange_order
            ),
        )

        # ---------------------------------------------
        # Atomic local accounting.
        # Either EVERYTHING persists or nothing does.
        # ---------------------------------------------

        conn = self.database.connect()

        try:

            conn.execute(
                "BEGIN IMMEDIATE"
            )

            self.accounting.apply_existing_order(
                conn,
                order_id=order_id,
                order=executed_order,
            )

            self.repository.mark_accounted(
                conn,
                order_id=order_id,
            )

            conn.commit()

        except Exception:

            conn.rollback()
            raise

        finally:

            conn.close()

        return ReconcileResult(
            order_id=order_id,
            client_order_id=(
                client_order_id
            ),
            result="ACCOUNTED",
            exchange_status=(
                exchange_status
            ),
            fills=len(fills),
            message=(
                "Exchange fills reconciled "
                "into ETF ledger."
            ),
        )
