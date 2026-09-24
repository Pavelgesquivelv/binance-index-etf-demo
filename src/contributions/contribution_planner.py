from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
WEIGHT_TOLERANCE = Decimal("0.00000001")


@dataclass(frozen=True)
class ContributionAllocation:
    asset: str
    target_weight_pct: Decimal
    quote_amount: Decimal

    @property
    def action(self) -> str:
        return "BUY"


@dataclass(frozen=True)
class ContributionPlan:
    period_id: str
    currency: str
    contribution_amount: Decimal
    allocations: tuple[
        ContributionAllocation,
        ...
    ]

    @property
    def allocated_amount(self) -> Decimal:
        return sum(
            (
                line.quote_amount
                for line in self.allocations
            ),
            ZERO,
        )

    @property
    def residual_amount(self) -> Decimal:
        return (
            self.contribution_amount
            - self.allocated_amount
        )


class ContributionPlanner:

    def build(
        self,
        *,
        feed,
        amount: Decimal,
        currency: str,
        period_id: str,
    ) -> ContributionPlan:

        amount = Decimal(amount)

        if amount <= ZERO:
            raise ValueError(
                "Contribution amount must "
                "be greater than zero."
            )

        if not period_id.strip():
            raise ValueError(
                "Contribution period_id "
                "cannot be empty."
            )

        positions = tuple(
            feed.positions
        )

        if not positions:
            raise ValueError(
                "Portfolio feed contains "
                "no positions."
            )

        total_weight = sum(
            (
                Decimal(
                    str(
                        item.target_weight_pct
                    )
                )
                for item in positions
            ),
            ZERO,
        )

        if (
            abs(
                total_weight
                - ONE_HUNDRED
            )
            > WEIGHT_TOLERANCE
        ):
            raise ValueError(
                "Contribution portfolio "
                "weights must total 100%. "
                f"Found {total_weight}%."
            )

        allocations = []

        for item in positions:

            weight = Decimal(
                str(
                    item.target_weight_pct
                )
            )

            if weight <= ZERO:
                raise ValueError(
                    f"{item.asset}: "
                    "target weight must "
                    "be positive."
                )

            quote_amount = (
                amount
                * weight
                / ONE_HUNDRED
            )

            allocations.append(
                ContributionAllocation(
                    asset=(
                        item.asset.upper()
                    ),
                    target_weight_pct=(
                        weight
                    ),
                    quote_amount=(
                        quote_amount
                    ),
                )
            )

        plan = ContributionPlan(
            period_id=period_id,
            currency=currency.upper(),
            contribution_amount=amount,
            allocations=tuple(
                allocations
            ),
        )

        if (
            abs(plan.residual_amount)
            > Decimal("0.00000001")
        ):
            raise RuntimeError(
                "Contribution allocation "
                "does not reconcile to the "
                "requested amount. "
                f"amount={amount}, "
                f"allocated="
                f"{plan.allocated_amount}, "
                f"residual="
                f"{plan.residual_amount}"
            )

        return plan
