from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_investment import (
    build_order_intents,
)
from src.contributions.contribution_planner import (
    ContributionPlanner,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)


feed = PortfolioFeedLoader(
    ROOT
    / "examples"
    / "portfolio.example.json"
).load()


plan = ContributionPlanner().build(
    feed=feed,
    amount=Decimal("200"),
    currency="USDC",
    period_id="2026-W40",
)


orders = build_order_intents(
    plan=plan,
    base_currency="USDC",
    order_prefix="IDXETF_",
)


assert len(orders) == 10

assert all(
    order.side == "BUY"
    for order in orders
)

assert sum(
    (
        order.quote_order_qty
        for order in orders
    ),
    Decimal("0"),
) == Decimal("200")


# BNB intentionally first.
assert orders[0].asset == "BNB"

assert (
    orders[0].client_order_id
    == "IDXETF_C2026W40_01_BNB"
)

assert len(
    {
        order.client_order_id
        for order in orders
    }
) == len(orders)


assert all(
    len(order.client_order_id) <= 36
    for order in orders
)


print(
    "Contribution investment test: OK"
)

print(
    "Orders              : "
    f"{len(orders)}"
)

print(
    "Sides               : BUY only"
)

print(
    "Total quote amount  : "
    f"{sum(o.quote_order_qty for o in orders)} "
    "USDC"
)

print()

for order in orders:

    print(
        f"{order.sequence:02d} "
        f"{order.client_order_id:30} "
        f"{order.symbol:12} "
        f"BUY "
        f"{order.quote_order_qty} USDC"
    )

print()

print(
    "Deterministic clientOrderIds: OK"
)
print(
    "No SELL intents             : OK"
)
