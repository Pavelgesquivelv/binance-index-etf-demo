from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")


@dataclass(frozen=True)
class OwnershipCheck:
    asset: str
    owned_quantity: Decimal
    required_quantity: Decimal

    @property
    def surplus(self) -> Decimal:
        return (
            self.owned_quantity
            - self.required_quantity
        )

    @property
    def ok(self) -> bool:
        return self.surplus >= ZERO


def check_owned_capacity(
    *,
    asset: str,
    owned_quantity: Decimal,
    required_quantity: Decimal,
) -> OwnershipCheck:

    asset = asset.upper()

    owned_quantity = Decimal(
        owned_quantity
    )

    required_quantity = Decimal(
        required_quantity
    )

    if owned_quantity < ZERO:
        raise RuntimeError(
            "Negative ETF-owned quantity "
            f"detected for {asset}: "
            f"{owned_quantity}"
        )

    if required_quantity < ZERO:
        raise RuntimeError(
            "Negative required execution "
            f"quantity for {asset}: "
            f"{required_quantity}"
        )

    return OwnershipCheck(
        asset=asset,
        owned_quantity=owned_quantity,
        required_quantity=(
            required_quantity
        ),
    )
