from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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


planner = ContributionPlanner()

plan = planner.build(
    feed=feed,
    amount=Decimal("200"),
    currency="USDC",
    period_id="2026-W40",
)


assert (
    plan.contribution_amount
    == Decimal("200")
)

assert (
    plan.allocated_amount
    == Decimal("200")
)

assert (
    plan.residual_amount
    == Decimal("0")
)

assert (
    len(plan.allocations)
    == len(feed.positions)
)

assert all(
    line.action == "BUY"
    for line in plan.allocations
)

assert all(
    line.quote_amount > 0
    for line in plan.allocations
)


by_asset = {
    line.asset: line
    for line in plan.allocations
}


# The current public example portfolio has
# ten equal-weight 10% constituents.
assert len(by_asset) == 10

for line in plan.allocations:

    assert (
        line.target_weight_pct
        == Decimal("10")
    )

    assert (
        line.quote_amount
        == Decimal("20")
    )


# Contribution amount must be positive.
try:

    planner.build(
        feed=feed,
        amount=Decimal("0"),
        currency="USDC",
        period_id="2026-W40",
    )

except ValueError:
    pass

else:
    raise AssertionError(
        "Zero contribution was not blocked."
    )


print(
    "Contribution planner test: OK"
)

print(
    "Period          : "
    f"{plan.period_id}"
)

print(
    "Contribution    : "
    f"{plan.contribution_amount} "
    f"{plan.currency}"
)

print(
    "Assets          : "
    f"{len(plan.allocations)}"
)

print(
    "Allocated       : "
    f"{plan.allocated_amount} "
    f"{plan.currency}"
)

print(
    "Residual        : "
    f"{plan.residual_amount} "
    f"{plan.currency}"
)

print()

for line in plan.allocations:

    print(
        f"{line.asset:6} "
        f"{line.target_weight_pct:>8}% "
        f"BUY "
        f"{line.quote_amount:>12} "
        f"{plan.currency}"
    )

print()

print(
    "BUY-only contribution allocation: OK"
)
