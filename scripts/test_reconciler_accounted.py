from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.accounting.execution_accounting import (
    ExecutionAccounting,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.execution.reconciler import (
    OrderReconciler,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.storage.database import (
    Database,
)


TEST_DB = (
    ROOT
    / "data"
    / "reconciler_accounted_test.db"
)

CLIENT_ORDER_ID = (
    "IDXETF_TEST_FILLED_01_BNB"
)


def cleanup():
    paths = (
        TEST_DB,
        Path(str(TEST_DB) + "-wal"),
        Path(str(TEST_DB) + "-shm"),
    )

    for path in paths:
        if path.exists():
            path.unlink()


class FakeBinanceClient:
    """
    Simulates the two read-only Binance calls
    used by OrderReconciler.

    No network request is made.
    """

    def get_order_if_exists(
        self,
        *,
        symbol: str,
        client_order_id: str,
    ) -> dict:

        assert symbol == "BNBUSDC"
        assert (
            client_order_id
            == CLIENT_ORDER_ID
        )

        return {
            "symbol": "BNBUSDC",
            "orderId": 987654321,
            "clientOrderId":
                CLIENT_ORDER_ID,
            "status": "FILLED",
            "side": "BUY",
            "type": "MARKET",
            "executedQty":
                "0.63300000",
            "cummulativeQuoteQty":
                "499.94973000",
        }

    def get_my_trades(
        self,
        *,
        symbol: str,
        order_id: int,
    ) -> list[dict]:

        assert symbol == "BNBUSDC"
        assert order_id == 987654321

        return [
            {
                "symbol": "BNBUSDC",
                "id": 555001,
                "orderId": 987654321,

                "price":
                    "789.81000000",

                "qty":
                    "0.63300000",

                "quoteQty":
                    "499.94973000",

                "commission":
                    "0.00015000",

                "commissionAsset":
                    "BNB",

                "isBuyer": True,
                "isMaker": False,
            }
        ]


def get_cash(
    conn,
    asset: str,
) -> Decimal:

    rows = conn.execute(
        """
        SELECT amount
        FROM cash_ledger
        WHERE asset = ?
        """,
        (asset,),
    ).fetchall()

    return sum(
        (
            Decimal(row["amount"])
            for row in rows
        ),
        Decimal("0"),
    )


def main():

    cleanup()

    database = Database(
        str(TEST_DB)
    )

    database.initialize_schema()

    ledger = PortfolioLedger(
        database
    )

    created = ledger.initialize_fund(
        fund_name="TEST ETF",
        base_currency="USDC",
        initial_capital=Decimal(
            "5000"
        ),
        shares_outstanding=Decimal(
            "50"
        ),
        order_prefix="IDXETF_",
    )

    assert created is True

    repository = OrderRepository()

    accounting = ExecutionAccounting(
        base_currency="USDC"
    )

    # -------------------------------------------------
    # Reserve order locally.
    # -------------------------------------------------

    with database.connection() as conn:

        run_id = (
            accounting.start_rebalance(
                conn,
                cutoff_utc="TEST",
                index_level=Decimal(
                    "100"
                ),
                nav_before=Decimal(
                    "5000"
                ),
            )
        )

        local_order_id = (
            repository.reserve_order(
                conn,
                rebalance_run_id=run_id,
                client_order_id=(
                    CLIENT_ORDER_ID
                ),
                symbol="BNBUSDC",
                asset="BNB",
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    Decimal("500")
                ),
            )
        )

    # -------------------------------------------------
    # Simulated recovery through Binance.
    # -------------------------------------------------

    with database.connection() as conn:

        recoverable = (
            repository
            .get_recoverable_orders(
                conn
            )
        )

    assert len(recoverable) == 1

    fake_client = (
        FakeBinanceClient()
    )

    reconciler = OrderReconciler(
        database=database,
        client=fake_client,
        base_currency="USDC",
    )

    result = (
        reconciler.reconcile_order(
            recoverable[0]
        )
    )

    # -------------------------------------------------
    # Inspect final persistent state.
    # -------------------------------------------------

    with database.connection() as conn:

        cash = get_cash(
            conn,
            "USDC",
        )

        position = conn.execute(
            """
            SELECT
                quantity,
                average_cost_usdc
            FROM positions
            WHERE asset = 'BNB'
            """
        ).fetchone()

        fee = conn.execute(
            """
            SELECT
                asset,
                amount
            FROM fee_ledger
            WHERE order_id = ?
            """,
            (local_order_id,),
        ).fetchone()

        lifecycle = conn.execute(
            """
            SELECT local_status
            FROM order_lifecycle
            WHERE order_id = ?
            """,
            (local_order_id,),
        ).fetchone()

        order_row = conn.execute(
            """
            SELECT
                exchange_order_id,
                exchange_status,
                executed_quantity,
                cumulative_quote_quantity
            FROM orders
            WHERE id = ?
            """,
            (local_order_id,),
        ).fetchone()

        fill_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM fills
            WHERE order_id = ?
            """,
            (local_order_id,),
        ).fetchone()["n"]

        recoverable_after = (
            repository
            .get_recoverable_orders(
                conn
            )
        )

    bnb_quantity = Decimal(
        position["quantity"]
    )

    average_cost = Decimal(
        position[
            "average_cost_usdc"
        ]
    )

    # -------------------------------------------------
    # Expected accounting
    #
    # BUY:
    # +0.63300000 BNB
    #
    # FEE:
    # -0.00015000 BNB
    #
    # NET:
    # 0.63285000 BNB
    #
    # CASH:
    # 5000 - 499.94973000
    # = 4500.05027000
    # -------------------------------------------------

    assert result.result == "ACCOUNTED"

    assert cash == Decimal(
        "4500.05027000"
    )

    assert bnb_quantity == Decimal(
        "0.63285000"
    )

    assert average_cost == Decimal(
        "789.81000000"
    )

    assert fee["asset"] == "BNB"

    assert Decimal(
        fee["amount"]
    ) == Decimal(
        "0.00015000"
    )

    assert (
        lifecycle["local_status"]
        == "ACCOUNTED"
    )

    assert (
        order_row[
            "exchange_status"
        ]
        == "FILLED"
    )

    assert fill_count == 1

    assert len(
        recoverable_after
    ) == 0

    # -------------------------------------------------
    # Output
    # -------------------------------------------------

    print("=" * 80)
    print(
        "RECONCILER ACCOUNTED TEST"
    )
    print("=" * 80)

    print()
    print(
        f"Result             : "
        f"{result.result}"
    )

    print(
        f"Exchange status    : "
        f"{result.exchange_status}"
    )

    print(
        f"Fills              : "
        f"{result.fills}"
    )

    print()
    print(
        f"USDC cash          : "
        f"{cash}"
    )

    print(
        f"BNB gross bought   : "
        f"0.63300000"
    )

    print(
        f"BNB commission     : "
        f"{fee['amount']}"
    )

    print(
        f"BNB net position   : "
        f"{bnb_quantity}"
    )

    print(
        f"Average cost       : "
        f"{average_cost} USDC"
    )

    print()
    print(
        f"Lifecycle          : "
        f"{lifecycle['local_status']}"
    )

    print(
        f"Exchange order ID  : "
        f"{order_row['exchange_order_id']}"
    )

    print(
        f"Recoverable orders : "
        f"{len(recoverable_after)}"
    )

    print()
    print(
        "ACCOUNTING VALIDATION: OK"
    )

    print(
        "No Binance order was sent."
    )

    cleanup()


if __name__ == "__main__":
    main()
