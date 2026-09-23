from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.exchange.binance_demo_client import BinanceDemoClient
from src.index.portfolio_feed import PortfolioFeedLoader


def filter_map(symbol_info: dict) -> dict:
    return {
        item["filterType"]: item
        for item in symbol_info.get("filters", [])
    }


def main():
    # ---------------------------------------------------------
    # Load runtime configuration
    # ---------------------------------------------------------

    config_path = ROOT / "config" / "runtime.yaml"

    with config_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    base_currency = config["fund"]["base_currency"]

    portfolio_path = (
        ROOT
        / config["index_feed"]["portfolio_file"]
    )

    # ---------------------------------------------------------
    # Load index portfolio
    # ---------------------------------------------------------

    feed = PortfolioFeedLoader(
        portfolio_path
    ).load()

    # ---------------------------------------------------------
    # Load Binance Demo exchange information
    # ---------------------------------------------------------

    client = BinanceDemoClient()

    exchange_info = client.get_exchange_info()

    symbols = {
        item["symbol"]: item
        for item in exchange_info.get("symbols", [])
    }

    # ---------------------------------------------------------
    # Validate ETF execution markets
    # ---------------------------------------------------------

    print("=" * 95)
    print("ETF EXECUTION MARKET VALIDATION")
    print("=" * 95)

    print(
        f"Base currency : {base_currency}"
    )

    print(
        f"Constituents : {len(feed.positions)}"
    )

    print()

    valid = []
    invalid = []

    for position in feed.positions:
        execution_symbol = (
            f"{position.asset}{base_currency}"
        )

        info = symbols.get(execution_symbol)

        print("-" * 95)
        print(
            f"{position.asset} "
            f"-> {execution_symbol}"
        )

        if info is None:
            print("STATUS       : NOT FOUND")

            invalid.append(
                (
                    position.asset,
                    execution_symbol,
                    "symbol not found",
                )
            )

            continue

        status = info.get("status")

        print(
            f"STATUS       : {status}"
        )

        print(
            f"BASE         : "
            f"{info.get('baseAsset')}"
        )

        print(
            f"QUOTE        : "
            f"{info.get('quoteAsset')}"
        )

        print(
            f"ORDER TYPES  : "
            f"{', '.join(info.get('orderTypes', []))}"
        )

        filters = filter_map(info)

        # -----------------------------------------------------
        # PRICE_FILTER
        # -----------------------------------------------------

        price_filter = filters.get(
            "PRICE_FILTER"
        )

        if price_filter:
            print(
                "PRICE FILTER : "
                f"min={price_filter.get('minPrice')} "
                f"tick={price_filter.get('tickSize')}"
            )

        # -----------------------------------------------------
        # LOT_SIZE
        # -----------------------------------------------------

        lot_size = filters.get(
            "LOT_SIZE"
        )

        if lot_size:
            print(
                "LOT SIZE     : "
                f"minQty={lot_size.get('minQty')} "
                f"stepSize={lot_size.get('stepSize')} "
                f"maxQty={lot_size.get('maxQty')}"
            )

        # -----------------------------------------------------
        # MARKET_LOT_SIZE
        # -----------------------------------------------------

        market_lot = filters.get(
            "MARKET_LOT_SIZE"
        )

        if market_lot:
            print(
                "MARKET LOT   : "
                f"minQty={market_lot.get('minQty')} "
                f"stepSize={market_lot.get('stepSize')} "
                f"maxQty={market_lot.get('maxQty')}"
            )

        # -----------------------------------------------------
        # MIN_NOTIONAL / NOTIONAL
        # -----------------------------------------------------

        min_notional = filters.get(
            "MIN_NOTIONAL"
        )

        notional = filters.get(
            "NOTIONAL"
        )

        if min_notional:
            print(
                "MIN NOTIONAL : "
                f"{min_notional.get('minNotional')}"
            )

        if notional:
            print(
                "NOTIONAL     : "
                f"min={notional.get('minNotional')} "
                f"max={notional.get('maxNotional')}"
            )

        # -----------------------------------------------------
        # Final symbol validation
        # -----------------------------------------------------

        if status != "TRADING":
            invalid.append(
                (
                    position.asset,
                    execution_symbol,
                    f"status={status}",
                )
            )

        elif info.get("quoteAsset") != base_currency:
            invalid.append(
                (
                    position.asset,
                    execution_symbol,
                    "wrong quote asset",
                )
            )

        else:
            valid.append(
                execution_symbol
            )

    # ---------------------------------------------------------
    # Summary
    # ---------------------------------------------------------

    print()
    print("=" * 95)
    print("SUMMARY")
    print("=" * 95)

    print(
        f"Tradable markets : "
        f"{len(valid)}/{len(feed.positions)}"
    )

    if valid:
        print()
        print("VALID:")

        for symbol in valid:
            print(
                f"  {symbol}"
            )

    if invalid:
        print()
        print("INVALID:")

        for asset, symbol, reason in invalid:
            print(
                f"  {asset:6} "
                f"{symbol:12} "
                f"{reason}"
            )

    print()

    if invalid:
        print(
            "ETF market validation: FAILED"
        )
        print(
            "No trading should be enabled."
        )
    else:
        print(
            "ETF market validation: OK"
        )
        print(
            "All constituents have a TRADING "
            f"{base_currency} market."
        )

    print()
    print(
        "No orders were sent."
    )


if __name__ == "__main__":
    main()
