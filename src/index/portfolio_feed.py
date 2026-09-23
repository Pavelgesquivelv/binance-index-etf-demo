from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


WEIGHT_TOLERANCE = Decimal("0.000001")


@dataclass(frozen=True)
class FeedPosition:
    asset: str
    source_pair: str
    target_weight_pct: Decimal

    @property
    def weight(self) -> Decimal:
        return self.target_weight_pct / Decimal("100")


@dataclass(frozen=True)
class PortfolioFeed:
    status: str
    cutoff_local: str
    cutoff_utc: str
    ranking_date: str
    index_level: Decimal
    positions: tuple[FeedPosition, ...]

    @property
    def total_weight_pct(self) -> Decimal:
        return sum(
            (
                position.target_weight_pct
                for position in self.positions
            ),
            Decimal("0"),
        )

    def target_values(
        self,
        nav: Decimal,
    ) -> dict[str, Decimal]:
        if nav <= 0:
            raise ValueError("NAV must be positive.")

        return {
            position.asset:
                nav * position.weight
            for position in self.positions
        }


class PortfolioFeedLoader:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> PortfolioFeed:
        if not self.path.exists():
            raise FileNotFoundError(
                f"Portfolio feed not found: {self.path}"
            )

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as file:
            raw = json.load(file)

        positions_raw = raw.get("positions")

        if not positions_raw:
            raise ValueError(
                "Portfolio feed contains no positions."
            )

        positions = tuple(
            FeedPosition(
                asset=str(
                    item["asset"]
                ).upper().strip(),
                source_pair=str(
                    item["pair"]
                ).upper().strip(),
                target_weight_pct=Decimal(
                    str(item["target_weight_pct"])
                ),
            )
            for item in positions_raw
        )

        feed = PortfolioFeed(
            status=str(
                raw.get("status", "")
            ),
            cutoff_local=str(
                raw.get("cutoff_local", "")
            ),
            cutoff_utc=str(
                raw.get("cutoff_utc", "")
            ),
            ranking_date=str(
                raw.get("ranking_date", "")
            ),
            index_level=Decimal(
                str(raw["index_level"])
            ),
            positions=positions,
        )

        self._validate(feed)

        return feed

    @staticmethod
    def _validate(
        feed: PortfolioFeed,
    ) -> None:
        assets = [
            position.asset
            for position in feed.positions
        ]

        duplicates = {
            asset
            for asset in assets
            if assets.count(asset) > 1
        }

        if duplicates:
            raise ValueError(
                "Duplicate assets in portfolio feed: "
                + ", ".join(sorted(duplicates))
            )

        for position in feed.positions:
            if not position.asset:
                raise ValueError(
                    "Empty asset found."
                )

            if position.target_weight_pct <= 0:
                raise ValueError(
                    f"{position.asset}: "
                    "weight must be positive."
                )

            if position.target_weight_pct > 100:
                raise ValueError(
                    f"{position.asset}: "
                    "weight cannot exceed 100%."
                )

        difference = abs(
            Decimal("100")
            - feed.total_weight_pct
        )

        if difference > WEIGHT_TOLERANCE:
            raise ValueError(
                "Portfolio weights must sum to 100%. "
                f"Current total: "
                f"{feed.total_weight_pct}"
            )
