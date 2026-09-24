from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.portfolio.physical_backing import (
    check_physical_backing,
)


ETF_BNB = Decimal("0.62352350")
BNB_RESERVE = Decimal("0.02000000")
ONE_SAT = Decimal("0.00000001")


def account_with_bnb(
    quantity: Decimal,
) -> dict:

    return {
        "balances": [
            {
                "asset": "BNB",
                "free": str(quantity),
                "locked": "0",
            },
            {
                "asset": "BTC",
                "free": "0.00575000",
                "locked": "0",
            },
            {
                "asset": "USDC",
                "free": "100.00000000",
                "locked": "0",
            },
        ]
    }


positions = {
    "BNB": ETF_BNB,
    "BTC": Decimal("0.00575000"),
}


# Exact threshold must pass.
ok = check_physical_backing(
    cash=Decimal("100.00000000"),
    positions=positions,
    account=account_with_bnb(
        ETF_BNB + BNB_RESERVE
    ),
    base_currency="USDC",
    minimum_reserves={
        "BNB": BNB_RESERVE,
    },
)

assert ok.ok
assert not ok.deficits


# One satoshi of BNB below the threshold
# must block execution.
failed = check_physical_backing(
    cash=Decimal("100.00000000"),
    positions=positions,
    account=account_with_bnb(
        ETF_BNB
        + BNB_RESERVE
        - ONE_SAT
    ),
    base_currency="USDC",
    minimum_reserves={
        "BNB": BNB_RESERVE,
    },
)

assert not failed.ok
assert len(failed.deficits) == 1

deficit = failed.deficits[0]

assert deficit.asset == "BNB"
assert deficit.surplus == -ONE_SAT

print(
    "Physical backing threshold test: OK"
)

print(
    "Exact ETF inventory + reserve passes."
)

print(
    "A 0.00000001 BNB deficit is blocked."
)
