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


# =========================================================
# Core dashboard invariants.
# These must hold regardless of whether the ETF is:
#
# - freshly initialized
# - waiting for its first rebalance
# - already invested
# =========================================================

assert snapshot["base_currency"] == "USDC"

assert snapshot["shares"] > 0

assert snapshot["cash"] >= 0

assert isinstance(
    snapshot["current_feed_processed"],
    bool,
)

assert (
    snapshot["recoverable_orders"]
    >= 0
)

assert isinstance(
    snapshot["portfolio"],
    list,
)

assert snapshot[
    "live_nav"
] is not None

assert snapshot[
    "live_nav_per_share"
] is not None

assert (
    snapshot["live_nav"]
    >= 0
)

assert (
    snapshot["live_nav_per_share"]
    > 0
)

assert isinstance(
    snapshot["physical_backing_ok"],
    bool,
)


# =========================================================
# State-dependent consistency.
# =========================================================

if snapshot[
    "current_feed_processed"
]:
    assert len(
        snapshot["portfolio"]
    ) > 0


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
    f"Feed processed    : "
    f"{snapshot['current_feed_processed']}"
)

print(
    f"Recoverable orders: "
    f"{snapshot['recoverable_orders']}"
)

print(
    f"Physical backing  : "
    f"{snapshot['physical_backing_ok']}"
)

print()
print("Safety flags:")

for key, value in (
    snapshot["flags"].items()
):
    print(
        f"  {key}={value}"
    )
