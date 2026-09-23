from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")
TEN_THOUSAND = Decimal("10000")


@dataclass(frozen=True)
class ExecutionMetrics:
    side: str

    quantity: Decimal
    quote_quantity: Decimal

    average_fill_price: Decimal

    bid: Decimal
    ask: Decimal
    mid: Decimal

    benchmark_notional: Decimal

    spread_cost_usdc: Decimal
    slippage_cost_usdc: Decimal
    execution_cost_vs_mid_usdc: Decimal

    fee_cost_usdc: Decimal
    implementation_shortfall_usdc: Decimal

    execution_cost_bps: Decimal
    implementation_shortfall_bps: Decimal


def value_commission_usdc(
    *,
    commission: Decimal,
    commission_asset: str,
    base_asset: str,
    quote_asset: str,
    benchmark_mid: Decimal,
    bnb_mid_usdc: Decimal | None,
) -> Decimal | None:
    """
    Value an execution commission in quote currency.

    Examples for our ETF:
      USDC fee -> direct
      BTC fee  -> BTC amount * BTCUSDC benchmark mid
      BNB fee  -> BNB amount * BNBUSDC benchmark mid

    Returns None when the fee asset cannot be valued
    from the captured benchmark information.
    """

    if commission < ZERO:
        raise ValueError(
            "Commission cannot be negative."
        )

    fee_asset = commission_asset.upper()
    base_asset = base_asset.upper()
    quote_asset = quote_asset.upper()

    if fee_asset == quote_asset:
        return commission

    if fee_asset == base_asset:
        return (
            commission
            * benchmark_mid
        )

    if (
        fee_asset == "BNB"
        and bnb_mid_usdc is not None
    ):
        return (
            commission
            * bnb_mid_usdc
        )

    return None


def calculate_execution_metrics(
    *,
    side: str,
    quantity: Decimal,
    quote_quantity: Decimal,
    bid: Decimal,
    ask: Decimal,
    mid: Decimal,
    fee_cost_usdc: Decimal,
) -> ExecutionMetrics:

    side = side.upper()

    if side not in {
        "BUY",
        "SELL",
    }:
        raise ValueError(
            f"Unsupported side: {side}"
        )

    if quantity <= ZERO:
        raise ValueError(
            "Executed quantity must be positive."
        )

    if quote_quantity <= ZERO:
        raise ValueError(
            "Quote quantity must be positive."
        )

    if (
        bid <= ZERO
        or ask <= ZERO
        or mid <= ZERO
    ):
        raise ValueError(
            "Benchmark prices must be positive."
        )

    if ask < bid:
        raise ValueError(
            "Ask cannot be below bid."
        )

    average_fill_price = (
        quote_quantity
        / quantity
    )

    benchmark_notional = (
        mid
        * quantity
    )

    if side == "BUY":

        spread_cost = (
            ask - mid
        ) * quantity

        slippage_cost = (
            average_fill_price
            - ask
        ) * quantity

        execution_cost = (
            average_fill_price
            - mid
        ) * quantity

    else:

        spread_cost = (
            mid - bid
        ) * quantity

        slippage_cost = (
            bid
            - average_fill_price
        ) * quantity

        execution_cost = (
            mid
            - average_fill_price
        ) * quantity

    implementation_shortfall = (
        execution_cost
        + fee_cost_usdc
    )

    execution_cost_bps = (
        execution_cost
        / benchmark_notional
        * TEN_THOUSAND
    )

    implementation_shortfall_bps = (
        implementation_shortfall
        / benchmark_notional
        * TEN_THOUSAND
    )

    return ExecutionMetrics(
        side=side,
        quantity=quantity,
        quote_quantity=quote_quantity,
        average_fill_price=(
            average_fill_price
        ),
        bid=bid,
        ask=ask,
        mid=mid,
        benchmark_notional=(
            benchmark_notional
        ),
        spread_cost_usdc=(
            spread_cost
        ),
        slippage_cost_usdc=(
            slippage_cost
        ),
        execution_cost_vs_mid_usdc=(
            execution_cost
        ),
        fee_cost_usdc=(
            fee_cost_usdc
        ),
        implementation_shortfall_usdc=(
            implementation_shortfall
        ),
        execution_cost_bps=(
            execution_cost_bps
        ),
        implementation_shortfall_bps=(
            implementation_shortfall_bps
        ),
    )
