from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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

    with database.connection() as conn:

        orders = conn.execute(
            """
            SELECT
                o.id,
                o.client_order_id
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE o.asset = 'BNB'
              AND o.side = 'BUY'
              AND l.local_status = 'ACCOUNTED'
            ORDER BY o.id
            """
        ).fetchall()

        if len(orders) != 1:
            raise RuntimeError(
                "Repair requires exactly one "
                "accounted BNB BUY. "
                f"Found: {len(orders)}"
            )

        order_id = orders[0]["id"]

        sell_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE o.asset = 'BNB'
              AND o.side = 'SELL'
              AND l.local_status = 'ACCOUNTED'
            """
        ).fetchone()["n"]

        if sell_count != 0:
            raise RuntimeError(
                "BNB SELLs already exist; "
                "automatic repair blocked."
            )

        fills = conn.execute(
            """
            SELECT
                quantity,
                quote_quantity,
                commission,
                commission_asset
            FROM fills
            WHERE order_id = ?
            """,
            (order_id,),
        ).fetchall()

        gross_quantity = sum(
            (
                Decimal(row["quantity"])
                for row in fills
            ),
            Decimal("0"),
        )

        quote_cost = sum(
            (
                Decimal(
                    row["quote_quantity"]
                )
                for row in fills
            ),
            Decimal("0"),
        )

        base_fee = sum(
            (
                Decimal(
                    row["commission"]
                )
                for row in fills
                if (
                    row["commission_asset"]
                    .upper()
                    == "BNB"
                )
            ),
            Decimal("0"),
        )

        net_quantity = (
            gross_quantity
            - base_fee
        )

        expected_average_cost = (
            quote_cost
            / net_quantity
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

        if position is None:
            raise RuntimeError(
                "BNB position not found."
            )

        actual_quantity = Decimal(
            position["quantity"]
        )

        if actual_quantity != net_quantity:
            raise RuntimeError(
                "BNB quantity mismatch. "
                f"Ledger={actual_quantity} "
                f"Expected={net_quantity}"
            )

        old_average_cost = Decimal(
            position[
                "average_cost_usdc"
            ]
        )

        conn.execute(
            """
            UPDATE positions
            SET
                average_cost_usdc = ?,
                updated_at_utc = ?
            WHERE asset = 'BNB'
            """,
            (
                str(
                    expected_average_cost
                ),
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

    print("=" * 72)
    print("BNB COST BASIS REPAIR")
    print("=" * 72)

    print()
    print(
        f"Gross quantity : "
        f"{gross_quantity}"
    )

    print(
        f"BNB fee        : "
        f"{base_fee}"
    )

    print(
        f"Net quantity   : "
        f"{net_quantity}"
    )

    print(
        f"USDC cost      : "
        f"{quote_cost}"
    )

    print()
    print(
        f"Old avg cost   : "
        f"{old_average_cost}"
    )

    print(
        f"New avg cost   : "
        f"{expected_average_cost}"
    )

    print()
    print(
        "Repair completed."
    )


if __name__ == "__main__":
    main()
