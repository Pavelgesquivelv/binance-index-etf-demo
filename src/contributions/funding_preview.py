from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")


@dataclass(frozen=True)
class FundingPreview:
    actual_balance: Decimal
    effective_balance: Decimal
    simulated: bool


def resolve_funding_preview(
    *,
    actual_balance: Decimal,
    simulated_balance: Decimal | None,
) -> FundingPreview:

    actual_balance = Decimal(
        actual_balance
    )

    if actual_balance < ZERO:
        raise RuntimeError(
            "Actual contribution funding "
            "balance cannot be negative."
        )

    if simulated_balance is None:

        return FundingPreview(
            actual_balance=actual_balance,
            effective_balance=actual_balance,
            simulated=False,
        )

    simulated_balance = Decimal(
        simulated_balance
    )

    if simulated_balance < ZERO:
        raise ValueError(
            "Simulated funding balance "
            "cannot be negative."
        )

    return FundingPreview(
        actual_balance=actual_balance,
        effective_balance=simulated_balance,
        simulated=True,
    )


def apply_funding_reserve_override(
    *,
    minimum_reserves: dict[
        str,
        Decimal,
    ],
    currency: str,
    actual_funding: Decimal,
    effective_funding: Decimal,
) -> dict[str, Decimal]:

    currency = currency.upper()

    actual_funding = Decimal(
        actual_funding
    )

    effective_funding = Decimal(
        effective_funding
    )

    if (
        actual_funding < ZERO
        or effective_funding < ZERO
    ):
        raise ValueError(
            "Funding balances cannot "
            "be negative."
        )

    result = {
        asset.upper(): Decimal(value)
        for asset, value
        in minimum_reserves.items()
    }

    current_currency_reserve = (
        result.get(
            currency,
            ZERO,
        )
    )

    non_funding_reserve = (
        current_currency_reserve
        - actual_funding
    )

    if non_funding_reserve < ZERO:
        raise RuntimeError(
            "Minimum reserve state is "
            "inconsistent with contribution "
            "funding balance."
        )

    replacement = (
        non_funding_reserve
        + effective_funding
    )

    if replacement > ZERO:
        result[currency] = replacement
    else:
        result.pop(
            currency,
            None,
        )

    return result
