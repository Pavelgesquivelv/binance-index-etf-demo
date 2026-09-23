from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.accounting.execution_accounting import (
    ExecutionAccounting,
)
from src.execution.benchmark_repository import (
    ExecutionBenchmarkRepository,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.storage.database import Database


TEST_DB = (
    ROOT
    / "data"
    / "benchmark_test.db"
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

    accounting = ExecutionAccounting(
        base_currency="USDC"
    )

    orders = OrderRepository()

    benchmarks = (
        ExecutionBenchmarkRepository()
    )

    with database.connection() as conn:

        run_id = (
            accounting.start_rebalance(
                conn,
                cutoff_utc="TEST",
                index_level=Decimal("100"),
                nav_before=Decimal("5000"),
            )
        )

        order_id = (
            orders.reserve_order(
                conn,
                rebalance_run_id=run_id,
                client_order_id=(
                    "IDXETF_TEST_BENCHMARK"
                ),
                symbol="BTCUSDC",
                asset="BTC",
                side="BUY",
                requested_quantity=None,
                requested_quote_quantity=(
                    Decimal("500")
                ),
            )
        )

        benchmarks.record(
            conn,
            order_id=order_id,
            bid=Decimal("100"),
            ask=Decimal("101"),
            bnb_mid_usdc=(
                Decimal("800")
            ),
        )

    with database.connection() as conn:

        row = conn.execute(
            """
            SELECT *
            FROM execution_benchmarks
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchone()

    assert row is not None

    assert Decimal(
        row["bid_price"]
    ) == Decimal("100")

    assert Decimal(
        row["ask_price"]
    ) == Decimal("101")

    assert Decimal(
        row["mid_price"]
    ) == Decimal("100.5")

    assert Decimal(
        row["spread_abs"]
    ) == Decimal("1")

    assert Decimal(
        row["bnb_mid_usdc"]
    ) == Decimal("800")

    print("=" * 72)
    print("EXECUTION BENCHMARK TEST")
    print("=" * 72)

    print()
    print(
        f"Bid        : {row['bid_price']}"
    )

    print(
        f"Ask        : {row['ask_price']}"
    )

    print(
        f"Mid        : {row['mid_price']}"
    )

    print(
        f"Spread     : {row['spread_abs']}"
    )

    print(
        f"Spread bps : {row['spread_bps']}"
    )

    print(
        f"BNB mid    : {row['bnb_mid_usdc']}"
    )

    print()
    print(
        "BENCHMARK PERSISTENCE: OK"
    )

    cleanup()


if __name__ == "__main__":
    main()
