from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.monitoring.valuation import (
    calculate_valuation,
)


result = calculate_valuation(
    cash=Decimal("100"),
    positions={
        "BTC":
            Decimal("0.01"),
        "ETH":
            Decimal("1"),
    },
    mid_prices={
        "BTC":
            Decimal("50000"),
        "ETH":
            Decimal("2500"),
    },
    shares=Decimal("50"),
)


assert (
    result.market_value
    == Decimal("3000")
)

assert (
    result.nav
    == Decimal("3100")
)

assert (
    result.nav_per_share
    == Decimal("62")
)


print(
    "Valuation test: OK"
)

print(
    "Market value : 3000"
)

print(
    "NAV          : 3100"
)

print(
    "NAV/share    : 62"
)
