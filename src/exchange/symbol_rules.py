from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str

    quote_precision: int

    min_notional: Decimal

    min_qty: Decimal
    step_size: Decimal

    quote_order_qty_market_allowed: bool

    @classmethod
    def from_exchange_info(
        cls,
        info: dict,
    ) -> "SymbolRules":

        filters = {
            item["filterType"]: item
            for item in info.get("filters", [])
        }

        lot = filters.get("LOT_SIZE", {})
        market_lot = filters.get(
            "MARKET_LOT_SIZE",
            {},
        )

        # For MARKET orders Binance may provide
        # a dedicated MARKET_LOT_SIZE.
        #
        # Some symbols report zero values there,
        # meaning those particular restrictions
        # are effectively disabled.
        step_size = Decimal(
            str(
                market_lot.get(
                    "stepSize",
                    "0",
                )
            )
        )

        min_qty = Decimal(
            str(
                market_lot.get(
                    "minQty",
                    "0",
                )
            )
        )

        # Conservative fallback to LOT_SIZE.
        if step_size == 0:
            step_size = Decimal(
                str(
                    lot.get(
                        "stepSize",
                        "0",
                    )
                )
            )

        if min_qty == 0:
            min_qty = Decimal(
                str(
                    lot.get(
                        "minQty",
                        "0",
                    )
                )
            )

        notional_filter = (
            filters.get("NOTIONAL")
            or filters.get("MIN_NOTIONAL")
            or {}
        )

        min_notional = Decimal(
            str(
                notional_filter.get(
                    "minNotional",
                    "0",
                )
            )
        )

        return cls(
            symbol=str(
                info["symbol"]
            ),
            base_asset=str(
                info["baseAsset"]
            ),
            quote_asset=str(
                info["quoteAsset"]
            ),
            status=str(
                info["status"]
            ),
            quote_precision=int(
                info.get(
                    "quoteAssetPrecision",
                    8,
                )
            ),
            min_notional=min_notional,
            min_qty=min_qty,
            step_size=step_size,
            quote_order_qty_market_allowed=bool(
                info.get(
                    "quoteOrderQtyMarketAllowed",
                    False,
                )
            ),
        )
