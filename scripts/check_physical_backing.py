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
from src.portfolio.owned_reserves import (
    build_owned_minimum_reserves_from_database,
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

    dedicated_bnb_reserve = Decimal(
        config.get(
            "account_isolation",
            {},
        ).get(
            "dedicated_bnb_fee_reserve",
            "0",
        )
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
        minimum_reserves=(
            build_owned_minimum_reserves_from_database(
                database,
                base_currency=base_currency,
                dedicated_bnb_fee_reserve=(
                    dedicated_bnb_reserve
                ),
            )
        ),
    )

    print("=" * 125)
    print(
        "ETF PHYSICAL BACKING CHECK"
    )
    print("=" * 125)

    print()

    print(
        f"{'ASSET':8}"
        f"{'ETF LEDGER':>22}"
        f"{'FEE RESERVE':>22}"
        f"{'REQUIRED':>22}"
        f"{'BINANCE FREE':>22}"
        f"{'HEADROOM':>22}"
    )

    print("-" * 125)

    for line in result.lines:

        status = (
            "OK"
            if line.is_backed
            else "FAIL"
        )

        print(
            f"{line.asset:8}"
            f"{str(line.ledger_quantity):>22}"
            f"{str(line.required_reserve):>22}"
            f"{str(line.required_total):>22}"
            f"{str(line.exchange_free):>22}"
            f"{str(line.surplus):>22} "
            f"{status}"
        )

    print("-" * 125)

    print()

    print(
        "Dedicated BNB fee reserve : "
        f"{dedicated_bnb_reserve} BNB"
    )

    print()

    if result.ok:

        print(
            "PHYSICAL BACKING: OK"
        )

        print(
            "ETF inventory is fully backed "
            "and the configured dedicated fee "
            "reserve is intact."
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
                f"ledger="
                f"{line.ledger_quantity}, "
                f"reserve="
                f"{line.required_reserve}, "
                f"required="
                f"{line.required_total}, "
                f"Binance free="
                f"{line.exchange_free}, "
                f"deficit="
                f"{-line.surplus}"
            )

        raise SystemExit(2)


if __name__ == "__main__":
    main()
