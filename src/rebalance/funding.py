from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_DOWN

from src.rebalance.planner import (
    RebalanceLine,
    RebalancePlan,
)
from src.exchange.symbol_rules import (
    SymbolRules,
)


ZERO = Decimal("0")


@dataclass(frozen=True)
class FundingResult:
    sells: tuple[RebalanceLine, ...]
    buys: tuple[RebalanceLine, ...]
    skipped_buys: tuple[RebalanceLine, ...]

    initial_cash: Decimal
    estimated_sell_proceeds: Decimal
    buying_power: Decimal
    remaining_buying_power: Decimal


def floor_quote(
    value: Decimal,
    precision: int,
) -> Decimal:

    quantum = Decimal("1").scaleb(
        -precision
    )

    return value.quantize(
        quantum,
        rounding=ROUND_DOWN,
    )


def make_cash_feasible(
    *,
    plan: RebalancePlan,
    rules: dict[str, SymbolRules],
) -> FundingResult:

    sells = tuple(
        sorted(
            plan.sells,
            key=lambda line: line.asset,
        )
    )

    estimated_sell_proceeds = sum(
        (
            line.estimated_notional
            for line in sells
        ),
        ZERO,
    )

    buying_power = (
        plan.cash
        + estimated_sell_proceeds
    )

    remaining = buying_power

    # Same intended execution priority:
    # BNB first, then remaining assets.
    buy_candidates = sorted(
        plan.buys,
        key=lambda line: (
            0 if line.asset == "BNB" else 1,
            line.asset,
        ),
    )

    funded = []
    skipped = []

    for line in buy_candidates:

        required = (
            line.estimated_notional
        )

        if required <= remaining:

            funded.append(line)

            remaining -= required

            continue

        # -----------------------------------------
        # Partial quoteOrderQty BUY.
        # -----------------------------------------

        if (
            line.quote_order_qty
            is not None
        ):

            rule = rules[
                line.symbol
            ]

            capped_quote = floor_quote(
                remaining,
                rule.quote_precision,
            )

            if (
                capped_quote > ZERO
                and
                capped_quote
                >= rule.min_notional
            ):

                funded.append(
                    replace(
                        line,
                        quote_order_qty=(
                            capped_quote
                        ),
                        estimated_notional=(
                            capped_quote
                        ),
                    )
                )

                remaining -= capped_quote

                continue

        # Not enough buying power for even
        # a valid partial market order.
        skipped.append(line)

    return FundingResult(
        sells=sells,
        buys=tuple(funded),
        skipped_buys=tuple(skipped),
        initial_cash=plan.cash,
        estimated_sell_proceeds=(
            estimated_sell_proceeds
        ),
        buying_power=buying_power,
        remaining_buying_power=remaining,
    )
