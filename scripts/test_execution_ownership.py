from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.portfolio.execution_ownership import (
    check_owned_capacity,
)


# --------------------------------------------------
# BUY may spend ETF-owned cash.
# --------------------------------------------------

buy_ok = check_owned_capacity(
    asset="USDC",
    owned_quantity=Decimal("202.58529750"),
    required_quantity=Decimal("20"),
)

assert buy_ok.ok
assert (
    buy_ok.surplus
    == Decimal("182.58529750")
)


# --------------------------------------------------
# External Binance cash cannot rescue the ETF.
# --------------------------------------------------

buy_blocked = check_owned_capacity(
    asset="USDC",
    owned_quantity=Decimal("2.58529750"),
    required_quantity=Decimal("20"),
)

assert not buy_blocked.ok
assert (
    buy_blocked.surplus
    == Decimal("-17.41470250")
)


# --------------------------------------------------
# SELL may use only ETF-owned position.
# --------------------------------------------------

sell_ok = check_owned_capacity(
    asset="BNB",
    owned_quantity=Decimal("0.63841614"),
    required_quantity=Decimal("0.10000000"),
)

assert sell_ok.ok


sell_blocked = check_owned_capacity(
    asset="BNB",
    owned_quantity=Decimal("0.03841614"),
    required_quantity=Decimal("0.10000000"),
)

assert not sell_blocked.ok


# --------------------------------------------------
# Negative quantities are invalid.
# --------------------------------------------------

try:
    check_owned_capacity(
        asset="USDC",
        owned_quantity=Decimal("-1"),
        required_quantity=Decimal("1"),
    )

except RuntimeError:
    pass

else:
    raise AssertionError(
        "Negative ownership was not blocked."
    )


try:
    check_owned_capacity(
        asset="USDC",
        owned_quantity=Decimal("100"),
        required_quantity=Decimal("-1"),
    )

except RuntimeError:
    pass

else:
    raise AssertionError(
        "Negative requirement was not blocked."
    )


print(
    "Execution ownership guard test: OK"
)

print(
    "ETF cash ownership       : ENFORCED"
)

print(
    "ETF position ownership   : ENFORCED"
)

print(
    "External balance rescue  : BLOCKED"
)


# --------------------------------------------------
# Production-like isolation scenario.
#
# Binance may physically hold:
#   ETF cash             = 2.58529750
#   contribution reserve = 2000
#   unallocated buffer   = 476.6852
#
# Total exchange free is therefore much larger than
# ETF-owned cash. A 20 USDC ETF BUY must still block.
# --------------------------------------------------

etf_cash = Decimal("2.58529750")
exchange_free_usdc = Decimal("2479.27049750")
requested_buy = Decimal("20")

assert exchange_free_usdc > requested_buy

production_like_buy = (
    check_owned_capacity(
        asset="USDC",
        owned_quantity=etf_cash,
        required_quantity=requested_buy,
    )
)

assert not production_like_buy.ok

assert (
    production_like_buy.surplus
    == Decimal("-17.41470250")
)

print(
    "Production-like isolation : OK"
)

print(
    "Binance free USDC          : "
    f"{exchange_free_usdc}"
)

print(
    "ETF-owned USDC             : "
    f"{etf_cash}"
)

print(
    "Requested ETF BUY          : "
    f"{requested_buy}"
)

print(
    "External cash consumption  : BLOCKED"
)
