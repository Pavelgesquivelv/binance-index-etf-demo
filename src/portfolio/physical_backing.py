from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")


@dataclass(frozen=True)
class PhysicalBackingLine:
    asset: str
    ledger_quantity: Decimal
    exchange_free: Decimal
    surplus: Decimal

    @property
    def is_backed(self) -> bool:
        return self.surplus >= ZERO


@dataclass(frozen=True)
class PhysicalBackingResult:
    lines: tuple[PhysicalBackingLine, ...]

    @property
    def ok(self) -> bool:
        return all(
            line.is_backed
            for line in self.lines
        )

    @property
    def deficits(
        self,
    ) -> tuple[PhysicalBackingLine, ...]:

        return tuple(
            line
            for line in self.lines
            if not line.is_backed
        )


def _exchange_free_balances(
    account: dict,
) -> dict[str, Decimal]:

    return {
        row["asset"].upper():
            Decimal(row["free"])
        for row in account.get(
            "balances",
            [],
        )
    }


def check_physical_backing(
    *,
    cash: Decimal,
    positions: dict[str, Decimal],
    account: dict,
    base_currency: str,
) -> PhysicalBackingResult:

    base_currency = (
        base_currency.upper()
    )

    exchange_free = (
        _exchange_free_balances(
            account
        )
    )

    required = {
        base_currency: cash,
    }

    for asset, quantity in (
        positions.items()
    ):

        asset = asset.upper()

        if quantity < ZERO:
            raise RuntimeError(
                f"Negative ETF position "
                f"detected for {asset}: "
                f"{quantity}"
            )

        required[asset] = (
            required.get(
                asset,
                ZERO,
            )
            + quantity
        )

    lines = []

    for asset in sorted(required):

        ledger_quantity = (
            required[asset]
        )

        free_quantity = (
            exchange_free.get(
                asset,
                ZERO,
            )
        )

        lines.append(
            PhysicalBackingLine(
                asset=asset,
                ledger_quantity=(
                    ledger_quantity
                ),
                exchange_free=(
                    free_quantity
                ),
                surplus=(
                    free_quantity
                    - ledger_quantity
                ),
            )
        )

    return PhysicalBackingResult(
        lines=tuple(lines)
    )
