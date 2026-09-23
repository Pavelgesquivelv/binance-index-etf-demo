from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from src.exchange.symbol_rules import SymbolRules
from src.index.portfolio_feed import PortfolioFeed


ZERO = Decimal("0")


def floor_to_step(
    value: Decimal,
    step: Decimal,
) -> Decimal:
    if step <= 0:
        return value

    units = (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    )

    return units * step


def floor_decimal_places(
    value: Decimal,
    decimal_places: int,
) -> Decimal:
    quantum = Decimal("1").scaleb(
        -decimal_places
    )

    return value.quantize(
        quantum,
        rounding=ROUND_DOWN,
    )


@dataclass(frozen=True)
class RebalanceLine:
    asset: str
    symbol: str

    target_weight: Decimal

    owned_quantity: Decimal

    bid: Decimal
    ask: Decimal
    mid: Decimal

    current_value: Decimal
    target_value: Decimal
    delta_value: Decimal

    action: str

    order_quantity: Decimal | None
    quote_order_qty: Decimal | None

    estimated_notional: Decimal

    reason: str


@dataclass(frozen=True)
class RebalancePlan:
    nav: Decimal
    cash: Decimal
    market_value: Decimal

    lines: tuple[RebalanceLine, ...]

    @property
    def buys(self) -> tuple[RebalanceLine, ...]:
        return tuple(
            line
            for line in self.lines
            if line.action == "BUY"
        )

    @property
    def sells(self) -> tuple[RebalanceLine, ...]:
        return tuple(
            line
            for line in self.lines
            if line.action == "SELL"
        )

    @property
    def holds(self) -> tuple[RebalanceLine, ...]:
        return tuple(
            line
            for line in self.lines
            if line.action in {
                "HOLD",
                "DUST",
            }
        )


class RebalancePlanner:

    def build(
        self,
        *,
        feed: PortfolioFeed,
        cash: Decimal,
        positions: dict[str, Decimal],
        books: dict[str, dict[str, Decimal]],
        rules: dict[str, SymbolRules],
        base_currency: str,
    ) -> RebalancePlan:

        base_currency = base_currency.upper()

        feed_weights = {
            position.asset:
                position.weight
            for position in feed.positions
        }

        # Important:
        # also include ETF-owned assets that disappeared
        # from the new index feed.
        assets = sorted(
            set(feed_weights)
            | set(positions)
        )

        market_value = ZERO

        current_values: dict[str, Decimal] = {}

        # -----------------------------------------------------
        # Calculate current portfolio market value
        # -----------------------------------------------------

        for asset in assets:
            quantity = positions.get(
                asset,
                ZERO,
            )

            if quantity == 0:
                current_values[asset] = ZERO
                continue

            symbol = f"{asset}{base_currency}"

            book = books[symbol]

            mid = (
                book["bid"]
                + book["ask"]
            ) / Decimal("2")

            value = quantity * mid

            current_values[asset] = value
            market_value += value

        nav = cash + market_value

        if nav <= 0:
            raise ValueError(
                "ETF NAV must be positive."
            )

        lines: list[RebalanceLine] = []

        # -----------------------------------------------------
        # Calculate required rebalance
        # -----------------------------------------------------

        for asset in assets:

            symbol = f"{asset}{base_currency}"

            rule = rules[symbol]
            book = books[symbol]

            bid = book["bid"]
            ask = book["ask"]

            mid = (
                bid + ask
            ) / Decimal("2")

            owned_quantity = positions.get(
                asset,
                ZERO,
            )

            current_value = current_values.get(
                asset,
                ZERO,
            )

            target_weight = feed_weights.get(
                asset,
                ZERO,
            )

            target_value = (
                nav * target_weight
            )

            delta = (
                target_value
                - current_value
            )

            # -------------------------------------------------
            # HOLD
            # -------------------------------------------------

            if abs(delta) < rule.min_notional:
                lines.append(
                    RebalanceLine(
                        asset=asset,
                        symbol=symbol,
                        target_weight=target_weight,
                        owned_quantity=owned_quantity,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        current_value=current_value,
                        target_value=target_value,
                        delta_value=delta,
                        action="HOLD",
                        order_quantity=None,
                        quote_order_qty=None,
                        estimated_notional=ZERO,
                        reason=(
                            "Difference below "
                            "minimum notional."
                        ),
                    )
                )

                continue

            # -------------------------------------------------
            # BUY
            # -------------------------------------------------

            if delta > 0:

                if (
                    rule.quote_order_qty_market_allowed
                ):
                    quote_order_qty = (
                        floor_decimal_places(
                            delta,
                            rule.quote_precision,
                        )
                    )

                    estimated_quantity = (
                        quote_order_qty / ask
                    )

                    lines.append(
                        RebalanceLine(
                            asset=asset,
                            symbol=symbol,
                            target_weight=target_weight,
                            owned_quantity=owned_quantity,
                            bid=bid,
                            ask=ask,
                            mid=mid,
                            current_value=current_value,
                            target_value=target_value,
                            delta_value=delta,
                            action="BUY",
                            order_quantity=None,
                            quote_order_qty=quote_order_qty,
                            estimated_notional=quote_order_qty,
                            reason=(
                                "Market BUY using "
                                "quoteOrderQty."
                            ),
                        )
                    )

                    continue

                # Fallback if quoteOrderQty is not allowed.
                raw_quantity = delta / ask

                quantity = floor_to_step(
                    raw_quantity,
                    rule.step_size,
                )

                notional = quantity * ask

                if (
                    quantity < rule.min_qty
                    or notional < rule.min_notional
                ):
                    lines.append(
                        RebalanceLine(
                            asset=asset,
                            symbol=symbol,
                            target_weight=target_weight,
                            owned_quantity=owned_quantity,
                            bid=bid,
                            ask=ask,
                            mid=mid,
                            current_value=current_value,
                            target_value=target_value,
                            delta_value=delta,
                            action="DUST",
                            order_quantity=None,
                            quote_order_qty=None,
                            estimated_notional=ZERO,
                            reason=(
                                "Executable BUY below "
                                "exchange minimum."
                            ),
                        )
                    )

                    continue

                lines.append(
                    RebalanceLine(
                        asset=asset,
                        symbol=symbol,
                        target_weight=target_weight,
                        owned_quantity=owned_quantity,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        current_value=current_value,
                        target_value=target_value,
                        delta_value=delta,
                        action="BUY",
                        order_quantity=quantity,
                        quote_order_qty=None,
                        estimated_notional=notional,
                        reason=(
                            "Market BUY using "
                            "base quantity."
                        ),
                    )
                )

                continue

            # -------------------------------------------------
            # SELL
            # -------------------------------------------------

            required_value = -delta

            raw_quantity = (
                required_value / bid
            )

            raw_quantity = min(
                raw_quantity,
                owned_quantity,
            )

            quantity = floor_to_step(
                raw_quantity,
                rule.step_size,
            )

            notional = (
                quantity * bid
            )

            if (
                quantity <= 0
                or quantity < rule.min_qty
                or notional < rule.min_notional
            ):
                lines.append(
                    RebalanceLine(
                        asset=asset,
                        symbol=symbol,
                        target_weight=target_weight,
                        owned_quantity=owned_quantity,
                        bid=bid,
                        ask=ask,
                        mid=mid,
                        current_value=current_value,
                        target_value=target_value,
                        delta_value=delta,
                        action="DUST",
                        order_quantity=None,
                        quote_order_qty=None,
                        estimated_notional=ZERO,
                        reason=(
                            "Required SELL below "
                            "exchange minimum."
                        ),
                    )
                )

                continue

            lines.append(
                RebalanceLine(
                    asset=asset,
                    symbol=symbol,
                    target_weight=target_weight,
                    owned_quantity=owned_quantity,
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    current_value=current_value,
                    target_value=target_value,
                    delta_value=delta,
                    action="SELL",
                    order_quantity=quantity,
                    quote_order_qty=None,
                    estimated_notional=notional,
                    reason=(
                        "Market SELL using "
                        "ETF-owned quantity only."
                    ),
                )
            )

        # Sells first, then buys.
        ordering = {
            "SELL": 0,
            "BUY": 1,
            "HOLD": 2,
            "DUST": 3,
        }

        lines.sort(
            key=lambda line: (
                ordering[line.action],
                line.asset,
            )
        )

        return RebalancePlan(
            nav=nav,
            cash=cash,
            market_value=market_value,
            lines=tuple(lines),
        )
