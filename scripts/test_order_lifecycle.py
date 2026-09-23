from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.accounting.execution_accounting import (
    ExecutionAccounting,
)
from src.execution.order_repository import (
    OrderRepository,
)
from src.storage.database import Database


def main():

    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    database = Database(
        str(
            ROOT
            / config["storage"]["database"]
        )
    )

    repo = OrderRepository()

    accounting = ExecutionAccounting(
        base_currency="USDC"
    )

    conn = database.connect()

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        run_id = accounting.start_rebalance(
            conn,
            cutoff_utc=(
                "TEST_ONLY"
            ),
            index_level=Decimal("100"),
            nav_before=Decimal("5000"),
        )

        client_order_id = (
            "IDXETF_TEST_R000001_01_BTC"
        )

        order_id = repo.reserve_order(
            conn,
            rebalance_run_id=run_id,
            client_order_id=client_order_id,
            symbol="BTCUSDC",
            asset="BTC",
            side="BUY",
            requested_quantity=None,
            requested_quote_quantity=(
                Decimal("500")
            ),
        )

        print("=" * 80)
        print("ORDER LIFECYCLE TEST")
        print("=" * 80)

        print()
        print(
            f"Reserved order ID : {order_id}"
        )

        rows = repo.get_recoverable_orders(
            conn
        )

        print()
        print("After reservation:")

        for row in rows:
            print(
                f"{row['client_order_id']} "
                f"local={row['local_status']} "
                f"exchange={row['exchange_status']}"
            )

        # Simulate Binance response.
        fake_response = {
            "symbol": "BTCUSDC",
            "orderId": 123456789,
            "clientOrderId":
                client_order_id,
            "status": "FILLED",
            "executedQty": "0.00570000",
            "cummulativeQuoteQty":
                "499.50000000",
        }

        repo.mark_exchange_ack(
            conn,
            order_id=order_id,
            response=fake_response,
        )

        rows = repo.get_recoverable_orders(
            conn
        )

        print()
        print("After fake exchange ACK:")

        for row in rows:
            print(
                f"{row['client_order_id']} "
                f"local={row['local_status']} "
                f"exchange={row['exchange_status']} "
                f"exchangeOrderId="
                f"{row['exchange_order_id']}"
            )

        repo.mark_accounted(
            conn,
            order_id=order_id,
        )

        rows = repo.get_recoverable_orders(
            conn
        )

        print()
        print(
            "After accounting:"
        )

        print(
            f"Recoverable orders: "
            f"{len(rows)}"
        )

        # Critical:
        # discard the entire test.
        conn.rollback()

        print()
        print("=" * 80)
        print("ROLLBACK COMPLETE")
        print("=" * 80)

        print(
            "No lifecycle test records "
            "were persisted."
        )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    main()
