from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.exchange.symbol_rules import (
    SymbolRules,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.rebalance.funding import (
    make_cash_feasible,
)
from src.rebalance.planner import (
    RebalancePlanner,
)
from src.storage.database import (
    Database,
)


ZERO = Decimal("0")


def load_config() -> dict:

    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:

        return yaml.safe_load(file)


def get_positions(
    ledger: PortfolioLedger,
) -> dict[str, Decimal]:

    return {
        row["asset"]:
            Decimal(row["quantity"])
        for row in ledger.get_positions()
        if Decimal(row["quantity"]) != ZERO
    }


def main():

    # =====================================================
    # Configuration
    # =====================================================

    config = load_config()

    base_currency = (
        config["fund"][
            "base_currency"
        ].upper()
    )

    portfolio_path = (
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    )

    database_path = (
        ROOT
        / config["storage"][
            "database"
        ]
    )

    # =====================================================
    # Local ETF state
    # =====================================================

    database = Database(
        str(database_path)
    )

    ledger = PortfolioLedger(
        database
    )

    cash = ledger.get_cash_balance(
        base_currency
    )

    positions = get_positions(
        ledger
    )

    # =====================================================
    # Portfolio feed
    # =====================================================

    feed = PortfolioFeedLoader(
        portfolio_path
    ).load()

    # =====================================================
    # Binance market information
    # =====================================================

    client = BinanceDemoClient()

    exchange_info = (
        client.get_exchange_info()
    )

    exchange_symbols = {
        item["symbol"]: item
        for item
        in exchange_info["symbols"]
    }

    assets = sorted(
        {
            position.asset
            for position
            in feed.positions
        }
        | set(positions)
    )

    books: dict[
        str,
        dict[str, Decimal],
    ] = {}

    rules: dict[
        str,
        SymbolRules,
    ] = {}

    # =====================================================
    # Build live books and symbol rules
    # =====================================================

    for asset in assets:

        symbol = (
            f"{asset}"
            f"{base_currency}"
        )

        symbol_info = (
            exchange_symbols.get(
                symbol
            )
        )

        if symbol_info is None:

            raise RuntimeError(
                f"Required market "
                f"does not exist: "
                f"{symbol}"
            )

        if (
            symbol_info["status"]
            != "TRADING"
        ):

            raise RuntimeError(
                f"{symbol} is not "
                "currently TRADING."
            )

        rules[symbol] = (
            SymbolRules
            .from_exchange_info(
                symbol_info
            )
        )

        ticker = (
            client.get_book_ticker(
                symbol
            )
        )

        books[symbol] = {
            "bid": Decimal(
                ticker["bidPrice"]
            ),
            "ask": Decimal(
                ticker["askPrice"]
            ),
        }

    # =====================================================
    # Build theoretical rebalance
    # =====================================================

    planner = RebalancePlanner()

    plan = planner.build(
        feed=feed,
        cash=cash,
        positions=positions,
        books=books,
        rules=rules,
        base_currency=base_currency,
    )

    # =====================================================
    # Convert theoretical plan into a cash-feasible plan
    # =====================================================

    funding = make_cash_feasible(
        plan=plan,
        rules=rules,
    )

    funded_buy_symbols = {
        line.symbol
        for line
        in funding.buys
    }

    funded_sell_symbols = {
        line.symbol
        for line
        in funding.sells
    }

    skipped_buy_symbols = {
        line.symbol
        for line
        in funding.skipped_buys
    }

    executable_lines = (
        list(funding.sells)
        + list(funding.buys)
    )

    # =====================================================
    # Header
    # =====================================================

    print("=" * 114)
    print(
        "ETF REBALANCE PREVIEW - "
        "DRY RUN"
    )
    print("=" * 114)

    print()

    print(
        f"Cash                  : "
        f"{plan.cash:.8f} "
        f"{base_currency}"
    )

    print(
        f"Current market value  : "
        f"{plan.market_value:.8f} "
        f"{base_currency}"
    )

    print(
        f"Calculated ETF NAV    : "
        f"{plan.nav:.8f} "
        f"{base_currency}"
    )

    print()

    # =====================================================
    # Portfolio detail
    # =====================================================

    print(
        f"{'ASSET':6} "
        f"{'ACTION':10} "
        f"{'WEIGHT':>10} "
        f"{'CURRENT':>14} "
        f"{'TARGET':>14} "
        f"{'DELTA':>14} "
        f"{'BID':>14} "
        f"{'ASK':>14}"
    )

    print("-" * 114)

    for line in plan.lines:

        display_action = (
            line.action
        )

        # ---------------------------------------------
        # The theoretical planner may identify a BUY,
        # but funding determines whether the ETF can
        # actually finance it.
        # ---------------------------------------------

        if (
            line.action == "BUY"
            and
            line.symbol
            in skipped_buy_symbols
        ):

            display_action = (
                "UNFUNDED"
            )

        print(
            f"{line.asset:6} "
            f"{display_action:10} "
            f"{line.target_weight * Decimal('100'):9.4f}% "
            f"{line.current_value:14.4f} "
            f"{line.target_value:14.4f} "
            f"{line.delta_value:14.4f} "
            f"{line.bid:14.8f} "
            f"{line.ask:14.8f}"
        )

        # ---------------------------------------------
        # Display actual executable order parameters,
        # not theoretical ones.
        # ---------------------------------------------

        funded_line = None

        if (
            line.symbol
            in funded_buy_symbols
        ):

            funded_line = next(
                item
                for item
                in funding.buys
                if (
                    item.symbol
                    == line.symbol
                )
            )

        elif (
            line.symbol
            in funded_sell_symbols
        ):

            funded_line = next(
                item
                for item
                in funding.sells
                if (
                    item.symbol
                    == line.symbol
                )
            )

        if funded_line is not None:

            if (
                funded_line
                .quote_order_qty
                is not None
            ):

                print(
                    "       "
                    f"MARKET "
                    f"{funded_line.action} "
                    f"quoteOrderQty="
                    f"{funded_line.quote_order_qty} "
                    f"{base_currency}"
                )

            elif (
                funded_line
                .order_quantity
                is not None
            ):

                print(
                    "       "
                    f"MARKET "
                    f"{funded_line.action} "
                    f"quantity="
                    f"{funded_line.order_quantity}"
                )

        elif (
            line.symbol
            in skipped_buy_symbols
        ):

            print(
                "       "
                "No executable BUY: "
                "insufficient ETF buying "
                "power / Binance minimum."
            )

    print("-" * 114)

    # =====================================================
    # Funding summary
    # =====================================================

    planned_buys = sum(
        (
            line.estimated_notional
            for line
            in funding.buys
        ),
        ZERO,
    )

    planned_sells = sum(
        (
            line.estimated_notional
            for line
            in funding.sells
        ),
        ZERO,
    )

    planned_turnover = (
        planned_buys
        + planned_sells
    )

    hold_dust_count = sum(
        1
        for line in plan.lines
        if line.action
        in {
            "HOLD",
            "DUST",
        }
    )

    print()

    print(
        f"BUY orders  : "
        f"{len(funding.buys)}"
    )

    print(
        f"SELL orders : "
        f"{len(funding.sells)}"
    )

    print(
        f"HOLD/DUST   : "
        f"{hold_dust_count}"
    )

    print(
        f"UNFUNDED    : "
        f"{len(funding.skipped_buys)}"
    )

    print()

    print(
        f"Planned BUY notional  : "
        f"{planned_buys:.8f} "
        f"{base_currency}"
    )

    print(
        f"Planned SELL notional : "
        f"{planned_sells:.8f} "
        f"{base_currency}"
    )

    print()

    print(
        f"Initial cash          : "
        f"{funding.initial_cash:.8f} "
        f"{base_currency}"
    )

    print(
        f"Estimated SELL cash   : "
        f"{funding.estimated_sell_proceeds:.8f} "
        f"{base_currency}"
    )

    print(
        f"Projected buying power: "
        f"{funding.buying_power:.8f} "
        f"{base_currency}"
    )

    print(
        f"Projected remaining   : "
        f"{funding.remaining_buying_power:.8f} "
        f"{base_currency}"
    )

    # =====================================================
    # Binance /order/test preflight
    #
    # IMPORTANT:
    # only executable orders are validated.
    # =====================================================

    print()
    print("=" * 114)
    print(
        "BINANCE ORDER PREFLIGHT"
    )
    print("=" * 114)

    bnb_discount_detected = False

    if not executable_lines:

        print()
        print(
            "No executable orders "
            "require preflight."
        )

    else:

        for line in executable_lines:

            print()

            if (
                line.quote_order_qty
                is not None
            ):

                response = (
                    client.test_market_order(
                        symbol=line.symbol,
                        side=line.action,
                        quote_order_qty=str(
                            line.quote_order_qty
                        ),
                        compute_commission_rates=True,
                    )
                )

            else:

                response = (
                    client.test_market_order(
                        symbol=line.symbol,
                        side=line.action,
                        quantity=str(
                            line.order_quantity
                        ),
                        compute_commission_rates=True,
                    )
                )

            print(
                f"{line.symbol:12} "
                f"{line.action:4} "
                f"VALID"
            )

            standard = (
                response.get(
                    "standardCommissionForOrder",
                    {},
                )
            )

            special = (
                response.get(
                    "specialCommissionForOrder",
                    {},
                )
            )

            tax = (
                response.get(
                    "taxCommissionForOrder",
                    {},
                )
            )

            discount = (
                response.get(
                    "discount",
                    {},
                )
            )

            print(
                "Standard commission: "
                f"maker="
                f"{standard.get('maker')} "
                f"taker="
                f"{standard.get('taker')}"
            )

            print(
                "Special commission : "
                f"maker="
                f"{special.get('maker')} "
                f"taker="
                f"{special.get('taker')}"
            )

            print(
                "Tax commission     : "
                f"maker="
                f"{tax.get('maker')} "
                f"taker="
                f"{tax.get('taker')}"
            )

            print(
                "Fee discount       : "
                f"account="
                f"{discount.get('enabledForAccount')} "
                f"symbol="
                f"{discount.get('enabledForSymbol')} "
                f"asset="
                f"{discount.get('discountAsset')}"
            )

            if (
                discount.get(
                    "enabledForAccount"
                )
                and
                discount.get(
                    "enabledForSymbol"
                )
                and
                discount.get(
                    "discountAsset"
                )
                == "BNB"
            ):

                bnb_discount_detected = True

    print()
    print("---")
    print()

    print(
        "Order parameter validation : OK"
    )

    # =====================================================
    # BNB fee reserve
    #
    # Only required when there are executable orders
    # and Binance reports the BNB discount.
    # =====================================================

    if (
        executable_lines
        and
        bnb_discount_detected
    ):

        account = (
            client.get_account()
        )

        taker_rate = Decimal(
            str(
                account.get(
                    "commissionRates",
                    {},
                ).get(
                    "taker",
                    "0",
                )
            )
        )

        conservative_fee_usdc = (
            planned_turnover
            * taker_rate
        )

        safety_multiplier = (
            Decimal("2")
        )

        required_fee_buffer = (
            conservative_fee_usdc
            * safety_multiplier
        )

        etf_bnb_quantity = (
            positions.get(
                "BNB",
                ZERO,
            )
        )

        bnb_symbol = (
            f"BNB{base_currency}"
        )

        bnb_book = (
            books.get(
                bnb_symbol
            )
        )

        if bnb_book is None:

            raise RuntimeError(
                "BNB fee discount active "
                "but BNB market data "
                "is unavailable."
            )

        bnb_mid = (
            bnb_book["bid"]
            + bnb_book["ask"]
        ) / Decimal("2")

        etf_bnb_value = (
            etf_bnb_quantity
            * bnb_mid
        )

        print()
        print(
            "BNB commission discount "
            "detected."
        )

        print(
            f"ETF-owned BNB     : "
            f"{etf_bnb_quantity}"
        )

        print(
            f"ETF BNB value     : "
            f"{etf_bnb_value:.8f} "
            f"{base_currency}"
        )

        print(
            f"Planned turnover  : "
            f"{planned_turnover:.8f} "
            f"{base_currency}"
        )

        print(
            f"Taker rate used   : "
            f"{taker_rate}"
        )

        print(
            f"Fee estimate      : "
            f"{conservative_fee_usdc:.8f} "
            f"{base_currency}"
        )

        print(
            f"Required 2x buffer: "
            f"{required_fee_buffer:.8f} "
            f"{base_currency}"
        )

        print()

        if (
            etf_bnb_value
            >= required_fee_buffer
        ):

            print(
                "BNB FEE RESERVE: OK"
            )

        else:

            print(
                "BNB FEE RESERVE: "
                "INSUFFICIENT"
            )

            raise RuntimeError(
                "ETF-owned BNB fee reserve "
                "is below the configured "
                "safety requirement."
            )

    # =====================================================
    # Funding explanation
    # =====================================================

    if funding.skipped_buys:

        print()
        print(
            "UNFUNDED BUY SIGNALS"
        )
        print("-" * 114)

        for line in (
            funding.skipped_buys
        ):

            print(
                f"{line.symbol:12} "
                f"requested="
                f"{line.estimated_notional:.8f} "
                f"{base_currency}"
            )

        print("-" * 114)

        print()

        print(
            "These are theoretical "
            "underweights, but they are "
            "not executable with the "
            "ETF's current buying power."
        )

    # =====================================================
    # Final status
    # =====================================================

    print()
    print(
        "DRY RUN ONLY - "
        "NO ORDERS WERE SENT"
    )


if __name__ == "__main__":
    main()