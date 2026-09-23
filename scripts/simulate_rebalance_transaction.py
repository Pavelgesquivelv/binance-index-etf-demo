from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.accounting.execution_accounting import (
    ExecutedOrder,
    ExecutionAccounting,
    ExecutionFill,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.exchange.symbol_rules import (
    SymbolRules,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)
from src.portfolio.ledger import PortfolioLedger
from src.rebalance.planner import (
    RebalancePlanner,
    floor_to_step,
)
from src.storage.database import Database


ZERO = Decimal("0")


def get_cash(
    conn,
    asset: str,
) -> Decimal:

    rows = conn.execute(
        """
        SELECT amount
        FROM cash_ledger
        WHERE asset = ?
        """,
        (asset,),
    ).fetchall()

    return sum(
        (
            Decimal(row["amount"])
            for row in rows
        ),
        ZERO,
    )


def get_positions(conn) -> dict[str, Decimal]:

    rows = conn.execute(
        """
        SELECT asset, quantity
        FROM positions
        ORDER BY asset
        """
    ).fetchall()

    return {
        row["asset"]:
            Decimal(row["quantity"])
        for row in rows
        if Decimal(row["quantity"]) != 0
    }


def get_mid(
    books: dict,
    symbol: str,
) -> Decimal:

    book = books[symbol]

    return (
        book["bid"]
        + book["ask"]
    ) / Decimal("2")


def get_commission_profile(
    response: dict,
) -> dict:

    standard = response.get(
        "standardCommissionForOrder",
        {},
    )

    special = response.get(
        "specialCommissionForOrder",
        {},
    )

    tax = response.get(
        "taxCommissionForOrder",
        {},
    )

    discount = response.get(
        "discount",
        {},
    )

    standard_taker = Decimal(
        str(
            standard.get(
                "taker",
                "0",
            )
        )
    )

    special_taker = Decimal(
        str(
            special.get(
                "taker",
                "0",
            )
        )
    )

    tax_taker = Decimal(
        str(
            tax.get(
                "taker",
                "0",
            )
        )
    )

    enabled = (
        bool(
            discount.get(
                "enabledForAccount",
                False,
            )
        )
        and bool(
            discount.get(
                "enabledForSymbol",
                False,
            )
        )
    )

    discount_rate = Decimal(
        str(
            discount.get(
                "discount",
                "0",
            )
        )
    )

    discount_asset = str(
        discount.get(
            "discountAsset",
            "",
        )
    ).upper()

    effective_standard = (
        standard_taker
    )

    if enabled:
        effective_standard *= (
            Decimal("1")
            - discount_rate
        )

    total_rate = (
        effective_standard
        + special_taker
        + tax_taker
    )

    return {
        "enabled": enabled,
        "discount_rate": discount_rate,
        "discount_asset": discount_asset,
        "total_rate": total_rate,
    }


def table_count(
    conn,
    table: str,
) -> int:

    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table}"
    ).fetchone()

    return int(row["n"])


def main():

    # =========================================================
    # Configuration
    # =========================================================

    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file)

    base_currency = (
        config["fund"]["base_currency"]
        .upper()
    )

    # =========================================================
    # Feed
    # =========================================================

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    # =========================================================
    # Database
    # =========================================================

    database = Database(
        str(
            ROOT
            / config["storage"][
                "database"
            ]
        )
    )

    ledger = PortfolioLedger(database)

    initial_cash = (
        ledger.get_cash_balance(
            base_currency
        )
    )

    initial_positions = {
        row["asset"]:
            Decimal(row["quantity"])
        for row in ledger.get_positions()
    }

    # =========================================================
    # Binance market data
    # =========================================================

    client = BinanceDemoClient()

    exchange_info = (
        client.get_exchange_info()
    )

    exchange_symbols = {
        item["symbol"]: item
        for item in exchange_info[
            "symbols"
        ]
    }

    feed_assets = {
        position.asset
        for position in feed.positions
    }

    assets = sorted(
        feed_assets
        | set(initial_positions)
    )

    books = {}
    rules = {}

    for asset in assets:

        symbol = (
            f"{asset}{base_currency}"
        )

        info = exchange_symbols[
            symbol
        ]

        rules[symbol] = (
            SymbolRules.from_exchange_info(
                info
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

    # =========================================================
    # Plan
    # =========================================================

    planner = RebalancePlanner()

    plan = planner.build(
        feed=feed,
        cash=initial_cash,
        positions=initial_positions,
        books=books,
        rules=rules,
        base_currency=base_currency,
    )

    # =========================================================
    # Binance preflight + commission profiles
    # =========================================================

    commission_profiles = {}

    for line in (
        list(plan.sells)
        + list(plan.buys)
    ):

        if line.quote_order_qty is not None:

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

        commission_profiles[
            line.symbol
        ] = get_commission_profile(
            response
        )

    # =========================================================
    # Execution order
    #
    # SELLs first.
    # If BNB fees are enabled, BNB BUY first.
    # =========================================================

    sells = list(plan.sells)
    buys = list(plan.buys)

    bnb_fees_active = any(
        profile["enabled"]
        and profile[
            "discount_asset"
        ] == "BNB"
        for profile
        in commission_profiles.values()
    )

    if bnb_fees_active:

        buys.sort(
            key=lambda line: (
                0
                if line.asset == "BNB"
                else 1,
                line.asset,
            )
        )

    execution_lines = (
        sells
        + buys
    )

    # =========================================================
    # Start SQLite transaction
    # =========================================================

    conn = database.connect()

    tables_to_check = [
        "rebalance_runs",
        "orders",
        "fills",
        "position_ledger",
        "fee_ledger",
    ]

    before_counts = {
        table:
            table_count(
                conn,
                table,
            )
        for table
        in tables_to_check
    }

    accounting = ExecutionAccounting(
        base_currency=base_currency
    )

    try:

        conn.execute(
            "BEGIN IMMEDIATE"
        )

        run_id = (
            accounting.start_rebalance(
                conn,
                cutoff_utc=feed.cutoff_utc,
                index_level=feed.index_level,
                nav_before=plan.nav,
            )
        )

        # Current BNB price for fee conversion
        bnb_symbol = (
            f"BNB{base_currency}"
        )

        bnb_mid = get_mid(
            books,
            bnb_symbol,
        )

        print("=" * 100)
        print(
            "SIMULATED ETF EXECUTION "
            "- SQLITE TRANSACTION"
        )
        print("=" * 100)

        print()
        print(
            f"NAV before       : "
            f"{plan.nav:.8f} "
            f"{base_currency}"
        )

        print(
            f"Cash before      : "
            f"{initial_cash:.8f} "
            f"{base_currency}"
        )

        print()

        # =====================================================
        # Simulated fills
        # =====================================================

        for sequence, line in enumerate(
            execution_lines,
            start=1,
        ):

            rule = rules[
                line.symbol
            ]

            profile = (
                commission_profiles[
                    line.symbol
                ]
            )

            if line.action == "BUY":

                execution_price = (
                    line.ask
                )

                if (
                    line.quote_order_qty
                    is not None
                ):

                    raw_quantity = (
                        line.quote_order_qty
                        / execution_price
                    )

                    quantity = (
                        floor_to_step(
                            raw_quantity,
                            rule.step_size,
                        )
                    )

                else:

                    quantity = (
                        line.order_quantity
                    )

                quote_quantity = (
                    quantity
                    * execution_price
                )

            else:

                execution_price = (
                    line.bid
                )

                quantity = (
                    line.order_quantity
                )

                quote_quantity = (
                    quantity
                    * execution_price
                )

            if (
                quantity is None
                or quantity <= 0
            ):
                raise RuntimeError(
                    f"Invalid simulated "
                    f"quantity for "
                    f"{line.symbol}"
                )

            # ---------------------------------------------
            # Simulate commission according to
            # current preflight profile
            # ---------------------------------------------

            fee_value_quote = (
                quote_quantity
                * profile["total_rate"]
            )

            if (
                profile["enabled"]
                and profile[
                    "discount_asset"
                ] == "BNB"
            ):

                commission_asset = (
                    "BNB"
                )

                commission = (
                    fee_value_quote
                    / bnb_mid
                )

            elif line.action == "BUY":

                commission_asset = (
                    line.asset
                )

                commission = (
                    fee_value_quote
                    / execution_price
                )

            else:

                commission_asset = (
                    base_currency
                )

                commission = (
                    fee_value_quote
                )

            fill = ExecutionFill(
                trade_id=(
                    f"SIMFILL{sequence:04d}"
                ),
                price=execution_price,
                quantity=quantity,
                quote_quantity=(
                    quote_quantity
                ),
                commission=commission,
                commission_asset=(
                    commission_asset
                ),
            )

            client_order_id = (
                f"IDXETF_SIM_"
                f"{sequence:02d}_"
                f"{line.asset}"
            )

            order = ExecutedOrder(
                client_order_id=(
                    client_order_id
                ),
                exchange_order_id=(
                    f"SIM{sequence:06d}"
                ),
                symbol=line.symbol,
                base_asset=line.asset,
                quote_asset=(
                    base_currency
                ),
                side=line.action,
                order_type="MARKET",
                status="FILLED",
                requested_quantity=(
                    line.order_quantity
                ),
                requested_quote_quantity=(
                    line.quote_order_qty
                ),
                fills=(fill,),
                response_payload={
                    "simulation": True,
                    "commissionProfile": {
                        key: str(value)
                        for key, value
                        in profile.items()
                    },
                },
            )

            accounting.apply_order(
                conn,
                rebalance_run_id=run_id,
                order=order,
            )

            print(
                f"{sequence:02d} "
                f"{line.symbol:12} "
                f"{line.action:4} "
                f"qty={quantity:<18} "
                f"quote="
                f"{quote_quantity:.8f} "
                f"fee="
                f"{commission:.12f} "
                f"{commission_asset}"
            )

        # =====================================================
        # Portfolio after simulated fills
        # =====================================================

        simulated_cash = get_cash(
            conn,
            base_currency,
        )

        simulated_positions = (
            get_positions(
                conn
            )
        )

        market_value = ZERO

        print()
        print("=" * 100)
        print("SIMULATED POSITIONS")
        print("=" * 100)

        for asset in sorted(
            simulated_positions
        ):

            quantity = (
                simulated_positions[
                    asset
                ]
            )

            symbol = (
                f"{asset}{base_currency}"
            )

            mid = get_mid(
                books,
                symbol,
            )

            value = (
                quantity
                * mid
            )

            market_value += value

            print(
                f"{asset:6} "
                f"qty="
                f"{quantity:<24} "
                f"value="
                f"{value:.8f} "
                f"{base_currency}"
            )

        simulated_nav = (
            simulated_cash
            + market_value
        )

        shares_row = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key =
                'shares_outstanding'
            """
        ).fetchone()

        shares = Decimal(
            shares_row["value"]
        )

        nav_per_share = (
            simulated_nav
            / shares
        )

        # =====================================================
        # Fee summary
        # =====================================================

        fee_rows = conn.execute(
            """
            SELECT
                asset,
                SUM(CAST(amount AS REAL))
                    AS amount
            FROM fee_ledger
            GROUP BY asset
            ORDER BY asset
            """
        ).fetchall()

        print()
        print("=" * 100)
        print("SIMULATED FEE SUMMARY")
        print("=" * 100)

        estimated_fee_value = ZERO

        for row in fee_rows:

            asset = row["asset"]

            amount = Decimal(
                str(row["amount"])
            )

            if asset == base_currency:

                value = amount

            else:

                symbol = (
                    f"{asset}"
                    f"{base_currency}"
                )

                value = (
                    amount
                    * get_mid(
                        books,
                        symbol,
                    )
                )

            estimated_fee_value += (
                value
            )

            print(
                f"{asset:6} "
                f"{amount:.12f} "
                f"(~{value:.8f} "
                f"{base_currency})"
            )

        accounting.finish_rebalance(
            conn,
            rebalance_run_id=run_id,
            status="SIMULATED",
            notes=(
                "Transaction rolled back "
                "after validation."
            ),
        )

        conn.execute(
            """
            INSERT INTO nav_snapshots (
                timestamp_utc,
                cash_usdc,
                market_value_usdc,
                nav_usdc,
                shares_outstanding,
                nav_per_share_usdc,
                index_level,
                tracking_difference
            )
            VALUES (
                datetime('now'),
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                str(simulated_cash),
                str(market_value),
                str(simulated_nav),
                str(shares),
                str(nav_per_share),
                str(feed.index_level),
                None,
            ),
        )

        print()
        print("=" * 100)
        print("SIMULATED NAV")
        print("=" * 100)

        print(
            f"Cash after       : "
            f"{simulated_cash:.8f} "
            f"{base_currency}"
        )

        print(
            f"Market value     : "
            f"{market_value:.8f} "
            f"{base_currency}"
        )

        print(
            f"NAV after        : "
            f"{simulated_nav:.8f} "
            f"{base_currency}"
        )

        print(
            f"NAV/share        : "
            f"{nav_per_share:.8f} "
            f"{base_currency}"
        )

        print(
            f"Est. fee value   : "
            f"{estimated_fee_value:.8f} "
            f"{base_currency}"
        )

        print()
        print(
            "Database state INSIDE "
            "transaction:"
        )

        for table in tables_to_check:

            print(
                f"  {table:20} "
                f"{table_count(conn, table)}"
            )

        # =====================================================
        # CRITICAL: discard entire simulation
        # =====================================================

        conn.rollback()

        print()
        print("=" * 100)
        print("ROLLBACK COMPLETE")
        print("=" * 100)

        print(
            "Simulation was NOT persisted."
        )

        print()

        after_counts = {
            table:
                table_count(
                    conn,
                    table,
                )
            for table
            in tables_to_check
        }

        for table in tables_to_check:

            before = before_counts[
                table
            ]

            after = after_counts[
                table
            ]

            status = (
                "OK"
                if before == after
                else "ERROR"
            )

            print(
                f"{table:20} "
                f"before={before:<5} "
                f"after={after:<5} "
                f"{status}"
            )

        final_cash = get_cash(
            conn,
            base_currency,
        )

        final_positions = (
            get_positions(
                conn
            )
        )

        print()
        print(
            f"Persistent cash  : "
            f"{final_cash} "
            f"{base_currency}"
        )

        print(
            f"Persistent "
            f"positions: "
            f"{len(final_positions)}"
        )

        print()
        print(
            "SIMULATION COMPLETE - "
            "NO BINANCE ORDERS SENT"
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


if __name__ == "__main__":
    main()
