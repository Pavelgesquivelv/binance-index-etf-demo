from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.index.portfolio_feed import PortfolioFeedLoader


def main():
    config_path = ROOT / "config" / "runtime.yaml"

    with config_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    portfolio_path = (
        ROOT
        / config["index_feed"]["portfolio_file"]
    )

    loader = PortfolioFeedLoader(
        portfolio_path
    )

    feed = loader.load()

    nav = Decimal("5000")

    targets = feed.target_values(nav)

    print("=" * 72)
    print("INDEX PORTFOLIO FEED")
    print("=" * 72)

    print(f"Status       : {feed.status}")
    print(f"Cutoff local : {feed.cutoff_local}")
    print(f"Cutoff UTC   : {feed.cutoff_utc}")
    print(f"Ranking date : {feed.ranking_date}")
    print(f"Index level  : {feed.index_level}")

    print()
    print(
        f"Constituents : {len(feed.positions)}"
    )

    print(
        f"Total weight : "
        f"{feed.total_weight_pct}%"
    )

    print()
    print("ETF TARGET PORTFOLIO")
    print("-" * 72)

    total_target = Decimal("0")

    for position in feed.positions:
        target = targets[position.asset]

        total_target += target

        execution_pair = (
            f"{position.asset}USDC"
        )

        print(
            f"{position.asset:6} "
            f"{position.target_weight_pct:>8}% "
            f"{target:>12} USDC "
            f"{execution_pair:12}"
        )

    print("-" * 72)

    print(
        f"{'TOTAL':6} "
        f"{feed.total_weight_pct:>8}% "
        f"{total_target:>12} USDC"
    )

    print()
    print(
        "Validation: OK - no orders were sent."
    )


if __name__ == "__main__":
    main()
