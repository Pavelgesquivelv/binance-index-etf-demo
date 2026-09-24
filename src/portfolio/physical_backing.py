from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal("0")


@dataclass(frozen=True)
class PhysicalBackingLine:
    asset: str
    ledger_quantity: Decimal
    required_reserve: Decimal
    exchange_free: Decimal
    surplus: Decimal

    @property
    def required_total(self) -> Decimal:
        return (
            self.ledger_quantity
            + self.required_reserve
        )

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
    minimum_reserves: dict[
        str,
        Decimal,
    ] | None = None,
) -> PhysicalBackingResult:

    base_currency = (
        base_currency.upper()
    )

    exchange_free = (
        _exchange_free_balances(
            account
        )
    )

    minimum_reserves = {
        asset.upper(): Decimal(value)
        for asset, value in (
            minimum_reserves or {}
        ).items()
    }

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

    all_assets = (
        set(required)
        | set(minimum_reserves)
    )

    lines = []

    for asset in sorted(all_assets):

        ledger_quantity = (
            required.get(
                asset,
                ZERO,
            )
        )

        required_reserve = (
            minimum_reserves.get(
                asset,
                ZERO,
            )
        )

        if required_reserve < ZERO:
            raise RuntimeError(
                f"Negative minimum reserve "
                f"detected for {asset}: "
                f"{required_reserve}"
            )

        free_quantity = (
            exchange_free.get(
                asset,
                ZERO,
            )
        )

        required_total = (
            ledger_quantity
            + required_reserve
        )

        lines.append(
            PhysicalBackingLine(
                asset=asset,
                ledger_quantity=(
                    ledger_quantity
                ),
                required_reserve=(
                    required_reserve
                ),
                exchange_free=(
                    free_quantity
                ),
                surplus=(
                    free_quantity
                    - required_total
                ),
            )
        )

    return PhysicalBackingResult(
        lines=tuple(lines)
    )
