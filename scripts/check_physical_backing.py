from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.portfolio.physical_backing import (
    check_physical_backing,
)
from src.storage.database import (
    Database,
)


def load_config() -> dict:

    with (
        ROOT
        / "config"
        / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(file)


def main():

    config = load_config()

    base_currency = (
        config["fund"][
            "base_currency"
        ].upper()
    )

    database = Database(
        str(
            ROOT
            / config["storage"][
                "database"
            ]
        )
    )

    ledger = PortfolioLedger(
        database
    )

    cash = ledger.get_cash_balance(
        base_currency
    )

    positions = {
        row["asset"]:
            Decimal(row["quantity"])
        for row in ledger.get_positions()
        if Decimal(
            row["quantity"]
        ) != 0
    }

    client = BinanceDemoClient()

    account = client.get_account()

    result = check_physical_backing(
        cash=cash,
        positions=positions,
        account=account,
        base_currency=base_currency,
    )

    print("=" * 92)
    print(
        "ETF PHYSICAL BACKING CHECK"
    )
    print("=" * 92)

    print()

    print(
        f"{'ASSET':8}"
        f"{'ETF LEDGER':>24}"
        f"{'BINANCE FREE':>24}"
        f"{'SURPLUS / DEFICIT':>24}"
    )

    print("-" * 92)

    for line in result.lines:

        status = (
            "OK"
            if line.is_backed
            else "FAIL"
        )

        print(
            f"{line.asset:8}"
            f"{str(line.ledger_quantity):>24}"
            f"{str(line.exchange_free):>24}"
            f"{str(line.surplus):>24} "
            f"{status}"
        )

    print("-" * 92)

    print()

    if result.ok:

        print(
            "PHYSICAL BACKING: OK"
        )

        print(
            "Every ETF ledger asset is "
            "fully covered by Binance "
            "free balance."
        )

    else:

        print(
            "PHYSICAL BACKING: FAILED"
        )

        print()

        print(
            "Deficits:"
        )

        for line in result.deficits:

            print(
                f"  {line.asset}: "
                f"ETF={line.ledger_quantity}, "
                f"Binance free="
                f"{line.exchange_free}, "
                f"deficit="
                f"{-line.surplus}"
            )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
