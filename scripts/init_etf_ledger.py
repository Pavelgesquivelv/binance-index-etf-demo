from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.portfolio.ledger import PortfolioLedger
from src.storage.database import Database


def load_config() -> dict:
    config_path = ROOT / "config" / "runtime.yaml"

    with config_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        return yaml.safe_load(file)


def main():
    config = load_config()

    fund = config["fund"]
    storage = config["storage"]

    database_path = ROOT / storage["database"]

    database = Database(
        str(database_path)
    )

    database.initialize_schema()

    ledger = PortfolioLedger(database)

    created = ledger.initialize_fund(
        fund_name=fund["name"],
        base_currency=fund["base_currency"],
        initial_capital=Decimal(
            fund["initial_capital"]
        ),
        shares_outstanding=Decimal(
            fund["shares_outstanding"]
        ),
        order_prefix=fund["order_prefix"],
    )

    if created:
        print("ETF ledger initialized successfully.")
    else:
        print(
            "ETF ledger already initialized. "
            "No capital was added."
        )

    print()
    print("Fund metadata")
    print("-" * 60)

    metadata = ledger.get_metadata()

    for key, value in metadata.items():
        print(
            f"{key:24}: {value}"
        )

    base_currency = fund["base_currency"]

    cash = ledger.get_cash_balance(
        base_currency
    )

    print()
    print(
        f"ETF cash balance         : "
        f"{cash} {base_currency}"
    )

    latest_nav = ledger.get_latest_nav()

    if latest_nav:
        print(
            f"ETF NAV                  : "
            f"{latest_nav['nav_usdc']} USDC"
        )

        print(
            f"Shares outstanding       : "
            f"{latest_nav['shares_outstanding']}"
        )

        print(
            f"NAV per share            : "
            f"{latest_nav['nav_per_share_usdc']} USDC"
        )


if __name__ == "__main__":
    main()
