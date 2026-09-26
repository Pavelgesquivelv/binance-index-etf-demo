from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.portfolio.physical_backing import (
    PhysicalBackingResult,
    check_physical_backing,
)


ZERO = Decimal("0")


@dataclass(frozen=True)
class FundingInitializationPlan:
    currency: str
    amount: Decimal
    current_funding: Decimal
    current_backing: PhysicalBackingResult
    proposed_backing: PhysicalBackingResult

    @property
    def proposed_funding(self) -> Decimal:
        return (
            self.current_funding
            + self.amount
        )

    @property
    def ok(self) -> bool:
        return (
            self.current_funding == ZERO
            and self.current_backing.ok
            and self.proposed_backing.ok
        )


def build_funding_initialization_plan(
    *,
    cash: Decimal,
    positions: dict[str, Decimal],
    account: dict,
    base_currency: str,
    current_reserves: dict[str, Decimal],
    amount: Decimal,
) -> FundingInitializationPlan:

    base_currency = (
        base_currency.upper()
    )

    amount = Decimal(amount)

    if amount <= ZERO:
        raise ValueError(
            "Initial contribution funding "
            "must be positive."
        )

    normalized_reserves = {
        asset.upper(): Decimal(value)
        for asset, value in (
            current_reserves.items()
        )
    }

    current_funding = (
        normalized_reserves.get(
            base_currency,
            ZERO,
        )
    )

    if current_funding != ZERO:
        raise RuntimeError(
            "Contribution funding must be "
            "zero before initialization. "
            f"{base_currency}="
            f"{current_funding}"
        )

    current_backing = (
        check_physical_backing(
            cash=Decimal(cash),
            positions=positions,
            account=account,
            base_currency=base_currency,
            minimum_reserves=(
                normalized_reserves
            ),
        )
    )

    if not current_backing.ok:
        raise RuntimeError(
            "Current ETF physical backing "
            "is not valid."
        )

    proposed_reserves = dict(
        normalized_reserves
    )

    proposed_reserves[
        base_currency
    ] = (
        proposed_reserves.get(
            base_currency,
            ZERO,
        )
        + amount
    )

    proposed_backing = (
        check_physical_backing(
            cash=Decimal(cash),
            positions=positions,
            account=account,
            base_currency=base_currency,
            minimum_reserves=(
                proposed_reserves
            ),
        )
    )

    if not proposed_backing.ok:

        deficits = "; ".join(
            (
                f"{line.asset}: "
                f"required="
                f"{line.required_total}, "
                f"free="
                f"{line.exchange_free}, "
                f"deficit="
                f"{-line.surplus}"
            )
            for line
            in proposed_backing.deficits
        )

        raise RuntimeError(
            "Insufficient physical backing "
            "for proposed contribution "
            f"funding. {deficits}"
        )

    return FundingInitializationPlan(
        currency=base_currency,
        amount=amount,
        current_funding=(
            current_funding
        ),
        current_backing=(
            current_backing
        ),
        proposed_backing=(
            proposed_backing
        ),
    )
