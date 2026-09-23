from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.accounting.execution_accounting import (
    ExecutionAccounting,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.execution.reconciler import (
    OrderReconciler,
)
from src.storage.database import Database


TEST_DB = (
    ROOT
    / "data"
    / "reconciler_test.db"
)


def cleanup():
    for path in (
        TEST_DB,
        Path(str(TEST_DB) + "-wal"),
        Path(str(TEST_DB) + "-shm"),
    ):
        if path.exists():
            path.unlink()


def main():

    cleanup()

    database = Database(
        str(TEST_DB)
    )

    database.initialize_schema()

    repository = OrderRepository()

    accounting = ExecutionAccounting(
        base_currency="USDC"
    )

    # ---------------------------------------------
    # Create and COMMIT a fake local reservation.
    # This simulates recovery after restart.
    # ---------------------------------------------

    with database.connection() as conn:

        run_id = accounting.start_rebalance(
            conn,
            cutoff_utc="TEST",
            index_level=Decimal("100"),
            nav_before=Decimal("5000"),
        )

        repository.reserve_order(
            conn,
            rebalance_run_id=run_id,
            client_order_id=(
                "IDXETF_TEST_NOORDER_260922"
            ),
            symbol="BTCUSDC",
            asset="BTC",
            side="BUY",
            requested_quantity=None,
            requested_quote_quantity=(
                Decimal("500")
            ),
        )


    with database.connection() as conn:

        recoverable = (
            repository
            .get_recoverable_orders(
                conn
            )
        )

    local_order = recoverable[0]

    # ---------------------------------------------
    # Real Binance query.
    # GET only. No order placement.
    # ---------------------------------------------

    client = BinanceDemoClient()

    reconciler = OrderReconciler(
        database=database,
        client=client,
        base_currency="USDC",
    )

    result = (
        reconciler.reconcile_order(
            local_order
        )
    )

    print("=" * 80)
    print("RECONCILER NOT-FOUND TEST")
    print("=" * 80)

    print()
    print(
        f"clientOrderId    : "
        f"{result.client_order_id}"
    )

    print(
        f"Result           : "
        f"{result.result}"
    )

    print(
        f"Exchange status  : "
        f"{result.exchange_status}"
    )

    print(
        f"Fills            : "
        f"{result.fills}"
    )

    print(
        f"Message          : "
        f"{result.message}"
    )

    with database.connection() as conn:

        remaining = (
            repository
            .get_recoverable_orders(
                conn
            )
        )

    print()
    print(
        f"Recoverable local orders: "
        f"{len(remaining)}"
    )

    if remaining:
        print(
            f"Local status     : "
            f"{remaining[0]['local_status']}"
        )

    print()
    print(
        "No Binance order was sent."
    )

    cleanup()


if __name__ == "__main__":
    main()
