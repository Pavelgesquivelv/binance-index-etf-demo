from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.funding_initialization import (
    build_funding_initialization_plan,
)


ZERO = Decimal("0")


account = {
    "balances": [
        {
            "asset": "USDC",
            "free": "2479.27049750",
        },
        {
            "asset": "BNB",
            "free": "0.66839477",
        },
        {
            "asset": "BTC",
            "free": "0.00595",
        },
    ]
}


plan = (
    build_funding_initialization_plan(
        cash=Decimal("2.58529750"),
        positions={
            "BTC": Decimal("0.00595"),
            "BNB": Decimal("0.63841614"),
        },
        account=account,
        base_currency="USDC",
        current_reserves={
            "BNB": Decimal("0.02000000"),
        },
        amount=Decimal("2000"),
    )
)


assert plan.ok

assert (
    plan.proposed_funding
    == Decimal("2000")
)


usdc = next(
    line
    for line in (
        plan.proposed_backing.lines
    )
    if line.asset == "USDC"
)


assert (
    usdc.required_total
    == Decimal("2002.58529750")
)

assert (
    usdc.exchange_free
    == Decimal("2479.27049750")
)

assert (
    usdc.surplus
    == Decimal("476.68520000")
)


# Existing funding must block.
try:

    build_funding_initialization_plan(
        cash=Decimal("2.58529750"),
        positions={},
        account=account,
        base_currency="USDC",
        current_reserves={
            "USDC": Decimal("200"),
        },
        amount=Decimal("2000"),
    )

except RuntimeError:
    pass

else:
    raise AssertionError(
        "Existing funding was not blocked."
    )


# Insufficient physical USDC must block.
poor_account = {
    "balances": [
        {
            "asset": "USDC",
            "free": "1500",
        }
    ]
}


try:

    build_funding_initialization_plan(
        cash=Decimal("2.58529750"),
        positions={},
        account=poor_account,
        base_currency="USDC",
        current_reserves={},
        amount=Decimal("2000"),
    )

except RuntimeError:
    pass

else:
    raise AssertionError(
        "Insufficient backing "
        "was not blocked."
    )


print(
    "Funding initialization test: OK"
)

print(
    "Initial reserve             : "
    "2000 USDC"
)

print(
    "Required owned USDC         : "
    "2002.58529750"
)

print(
    "Expected unallocated buffer : "
    "476.68520000"
)

print(
    "Duplicate initialization    : BLOCKED"
)

print(
    "Insufficient physical cash  : BLOCKED"
)
