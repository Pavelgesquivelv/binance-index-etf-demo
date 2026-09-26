from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.funding_preview import (
    apply_funding_reserve_override,
    resolve_funding_preview,
)


actual = resolve_funding_preview(
    actual_balance=Decimal("2000"),
    simulated_balance=None,
)

assert actual.actual_balance == Decimal("2000")
assert actual.effective_balance == Decimal("2000")
assert actual.simulated is False


simulated = resolve_funding_preview(
    actual_balance=Decimal("2000"),
    simulated_balance=Decimal("150"),
)

assert simulated.actual_balance == Decimal("2000")
assert simulated.effective_balance == Decimal("150")
assert simulated.simulated is True


reserves = (
    apply_funding_reserve_override(
        minimum_reserves={
            "USDC": Decimal("2000"),
            "BNB": Decimal("0.02000000"),
        },
        currency="USDC",
        actual_funding=Decimal("2000"),
        effective_funding=Decimal("150"),
    )
)

assert (
    reserves["USDC"]
    == Decimal("150")
)

assert (
    reserves["BNB"]
    == Decimal("0.02000000")
)


# Same-asset non-funding reserve preservation.
combined = (
    apply_funding_reserve_override(
        minimum_reserves={
            "BNB": Decimal("2.02"),
        },
        currency="BNB",
        actual_funding=Decimal("2"),
        effective_funding=Decimal("1"),
    )
)

assert (
    combined["BNB"]
    == Decimal("1.02")
)


negative_blocked = False

try:
    resolve_funding_preview(
        actual_balance=Decimal("2000"),
        simulated_balance=Decimal("-1"),
    )
except ValueError:
    negative_blocked = True

assert negative_blocked


print("Funding preview test: OK")
print("Actual funding        : 2000")
print("Simulated funding     : 150")
print("BNB reserve preserved : OK")
print("Negative simulation   : BLOCKED")
