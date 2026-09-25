from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.dashboard.data import (
    load_dashboard_snapshot,
)


snapshot = (
    load_dashboard_snapshot(
        ROOT
    )
)


assert snapshot["base_currency"] == "USDC"

assert snapshot["shares"] > 0

assert snapshot["cash"] >= 0

assert snapshot[
    "current_feed_processed"
] is True

assert (
    snapshot["recoverable_orders"]
    == 0
)

assert len(
    snapshot["portfolio"]
) == 10

assert snapshot[
    "live_nav"
] is not None

assert snapshot[
    "live_nav_per_share"
] is not None

assert snapshot[
    "physical_backing_ok"
] is True


print(
    "Dashboard data test: OK"
)

print(
    f"Cash              : "
    f"{snapshot['cash']:.8f} USDC"
)

print(
    f"Live market value : "
    f"{snapshot['live_market_value']:.8f} "
    f"USDC"
)

print(
    f"Live NAV          : "
    f"{snapshot['live_nav']:.8f} USDC"
)

print(
    f"NAV/share         : "
    f"{snapshot['live_nav_per_share']:.8f} "
    f"USDC"
)

print(
    f"Shares            : "
    f"{snapshot['shares']}"
)

print(
    f"Portfolio assets  : "
    f"{len(snapshot['portfolio'])}"
)

print(
    f"Recoverable orders: "
    f"{snapshot['recoverable_orders']}"
)

print(
    "Physical backing : OK"
)

print()
print("Safety flags:")

for key, value in (
    snapshot["flags"].items()
):
    print(
        f"  {key}={value}"
    )
