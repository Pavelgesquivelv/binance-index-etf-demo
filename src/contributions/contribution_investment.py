from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.contributions.contribution_planner import (
    ContributionPlan,
)


ZERO = Decimal("0")


@dataclass(frozen=True)
class ContributionOrderIntent:
    sequence: int
    asset: str
    symbol: str
    side: str
    quote_order_qty: Decimal
    target_weight_pct: Decimal
    client_order_id: str


def build_order_intents(
    *,
    plan: ContributionPlan,
    base_currency: str,
    order_prefix: str,
) -> tuple[
    ContributionOrderIntent,
    ...
]:

    if not order_prefix:
        raise ValueError(
            "order_prefix cannot be empty."
        )

    period_token = (
        plan.period_id.replace(
            "-",
            "",
        )
    )

    allocations = list(
        plan.allocations
    )

    # Buy BNB first when it is one of the
    # constituents. This increases fee-paying
    # inventory before the remaining BUYs.
    allocations.sort(
        key=lambda line: (
            0
            if line.asset == "BNB"
            else 1
        )
    )

    intents = []

    for sequence, allocation in enumerate(
        allocations,
        start=1,
    ):

        if allocation.action != "BUY":
            raise RuntimeError(
                "Contribution investment "
                "may only create BUY orders."
            )

        if allocation.quote_amount <= ZERO:
            raise RuntimeError(
                f"{allocation.asset}: "
                "quote amount must be positive."
            )

        client_order_id = (
            f"{order_prefix}"
            f"C{period_token}_"
            f"{sequence:02d}_"
            f"{allocation.asset}"
        )

        if len(client_order_id) > 36:
            raise RuntimeError(
                "clientOrderId exceeds "
                "Binance maximum length: "
                f"{client_order_id}"
            )

        intents.append(
            ContributionOrderIntent(
                sequence=sequence,
                asset=allocation.asset,
                symbol=(
                    f"{allocation.asset}"
                    f"{base_currency}"
                ),
                side="BUY",
                quote_order_qty=(
                    allocation.quote_amount
                ),
                target_weight_pct=(
                    allocation
                    .target_weight_pct
                ),
                client_order_id=(
                    client_order_id
                ),
            )
        )

    total = sum(
        (
            intent.quote_order_qty
            for intent in intents
        ),
        ZERO,
    )

    if total != plan.contribution_amount:
        raise RuntimeError(
            "Contribution order intents "
            "do not reconcile to accepted "
            "contribution amount. "
            f"expected="
            f"{plan.contribution_amount}, "
            f"orders={total}"
        )

    return tuple(intents)
