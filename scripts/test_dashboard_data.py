from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.dashboard.data import (
    load_dashboard_snapshot,
)


ZERO = Decimal("0")


snapshot = load_dashboard_snapshot(
    ROOT
)


# --------------------------------------------------
# Basic snapshot structure.
# --------------------------------------------------

assert snapshot["base_currency"] == "USDC"

assert snapshot["shares"] > ZERO

assert snapshot["cash"] >= ZERO

assert isinstance(
    snapshot["current_feed_processed"],
    bool,
)

assert (
    snapshot["recoverable_orders"]
    >= 0
)

assert snapshot[
    "live_nav"
] is not None

assert snapshot[
    "live_nav_per_share"
] is not None


# --------------------------------------------------
# Contribution funding ownership.
# --------------------------------------------------

funding_reserve = snapshot[
    "contribution_funding_reserve"
]

assert funding_reserve >= ZERO


# --------------------------------------------------
# Physical backing must be internally consistent.
#
# This test intentionally does NOT require backing
# to be True. A development DB may legitimately
# differ from the live Binance Demo account.
# --------------------------------------------------

physical_backing = snapshot[
    "physical_backing"
]

assert physical_backing

calculated_backing_ok = all(
    row["is_backed"]
    for row in physical_backing
)

assert (
    snapshot["physical_backing_ok"]
    == calculated_backing_ok
)


# --------------------------------------------------
# USDC ownership invariant.
#
# Required physical USDC must always equal:
#
# ETF ledger cash
# + contribution funding reserve
# --------------------------------------------------

usdc_backing = next(
    row
    for row in physical_backing
    if row["asset"] == "USDC"
)

assert (
    usdc_backing["ledger_quantity"]
    == snapshot["cash"]
)

assert (
    usdc_backing["required_reserve"]
    == funding_reserve
)

assert (
    usdc_backing["required"]
    == snapshot["cash"]
    + funding_reserve
)

assert (
    usdc_backing["surplus"]
    == usdc_backing["exchange_free"]
    - usdc_backing["required"]
)

assert (
    usdc_backing["is_backed"]
    == (
        usdc_backing["surplus"]
        >= ZERO
    )
)


# --------------------------------------------------
# Report.
# --------------------------------------------------

print(
    "Dashboard data test: OK"
)

print(
    f"ETF ledger cash       : "
    f"{snapshot['cash']:.8f} USDC"
)

print(
    f"Funding reserve       : "
    f"{funding_reserve:.8f} USDC"
)

print(
    f"USDC required total   : "
    f"{usdc_backing['required']:.8f} USDC"
)

print(
    f"Binance free USDC     : "
    f"{usdc_backing['exchange_free']:.8f} USDC"
)

print(
    f"USDC headroom         : "
    f"{usdc_backing['surplus']:.8f} USDC"
)

print(
    f"Current feed processed: "
    f"{snapshot['current_feed_processed']}"
)

print(
    f"Physical backing OK   : "
    f"{snapshot['physical_backing_ok']}"
)

print(
    "Dashboard invariants  : OK"
)
