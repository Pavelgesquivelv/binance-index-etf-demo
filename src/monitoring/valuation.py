from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")


@dataclass(frozen=True)
class ValuationResult:
    cash: Decimal
    market_value: Decimal
    nav: Decimal
    shares: Decimal
    nav_per_share: Decimal


def calculate_valuation(
    *,
    cash: Decimal,
    positions: dict[str, Decimal],
    mid_prices: dict[str, Decimal],
    shares: Decimal,
) -> ValuationResult:

    if cash < ZERO:
        raise ValueError(
            "ETF cash cannot be negative."
        )

    if shares <= ZERO:
        raise ValueError(
            "shares must be positive."
        )

    missing = (
        set(positions)
        - set(mid_prices)
    )

    if missing:
        raise ValueError(
            "Missing market prices for: "
            + ", ".join(
                sorted(missing)
            )
        )

    market_value = sum(
        (
            quantity
            * mid_prices[asset]
            for asset, quantity
            in positions.items()
        ),
        ZERO,
    )

    nav = (
        cash
        + market_value
    )

    return ValuationResult(
        cash=cash,
        market_value=market_value,
        nav=nav,
        shares=shares,
        nav_per_share=(
            nav / shares
        ),
    )
