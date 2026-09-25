from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from decimal import Decimal
from pathlib import Path
import sys

import yaml
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(
    ROOT / ".env"
)


from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)
from src.monitoring.valuation import (
    calculate_valuation,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.storage.database import (
    Database,
)


ZERO = Decimal("0")


def main():

    with (
        ROOT
        / "config"
        / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:

        config = yaml.safe_load(file)

    base_currency = (
        config["fund"][
            "base_currency"
        ]
        .upper()
    )

    database = Database(
        str(
            ROOT
            / config["storage"][
                "database"
            ]
        )
    )

    ledger = PortfolioLedger(
        database
    )

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    now = datetime.now(
        timezone.utc
    )

    bucket = now.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    bucket_utc = (
        bucket.isoformat()
    )

    # --------------------------------------------
    # Idempotency:
    # exactly one valuation per UTC hour.
    # --------------------------------------------

    with database.connection() as conn:

        existing = conn.execute(
            """
            SELECT
                id,
                captured_at_utc,
                nav_usdc,
                nav_per_share_usdc
            FROM valuation_snapshots
            WHERE bucket_utc = ?
            """,
            (
                bucket_utc,
            ),
        ).fetchone()

    if existing is not None:

        print(
            "Decision           : "
            "NO_ACTION_ALREADY_CAPTURED"
        )

        print(
            f"Bucket UTC         : "
            f"{bucket_utc}"
        )

        print(
            f"Snapshot ID        : "
            f"{existing['id']}"
        )

        print(
            f"NAV                : "
            f"{existing['nav_usdc']} "
            f"{base_currency}"
        )

        print(
            f"NAV/share          : "
            f"{existing['nav_per_share_usdc']} "
            f"{base_currency}"
        )

        return

    cash = ledger.get_cash_balance(
        base_currency
    )

    shares_text = ledger.get_meta(
        "shares_outstanding"
    )

    if shares_text is None:
        raise RuntimeError(
            "shares_outstanding is missing."
        )

    shares = Decimal(
        shares_text
    )

    positions = {
        row["asset"]:
            Decimal(
                row["quantity"]
            )
        for row in ledger.get_positions()
        if Decimal(
            row["quantity"]
        ) != ZERO
    }

    # --------------------------------------------
    # Binance Demo GET-only pricing.
    # No order endpoints are used.
    # --------------------------------------------

    client = BinanceDemoClient()

    mid_prices = {}

    for asset in sorted(
        positions
    ):

        symbol = (
            f"{asset}{base_currency}"
        )

        ticker = (
            client.get_book_ticker(
                symbol
            )
        )

        bid = Decimal(
            ticker["bidPrice"]
        )

        ask = Decimal(
            ticker["askPrice"]
        )

        if (
            bid <= ZERO
            or ask <= ZERO
            or ask < bid
        ):
            raise RuntimeError(
                f"Invalid book ticker "
                f"for {symbol}."
            )

        mid_prices[asset] = (
            bid + ask
        ) / Decimal("2")

    valuation = (
        calculate_valuation(
            cash=cash,
            positions=positions,
            mid_prices=mid_prices,
            shares=shares,
        )
    )

    captured_at_utc = (
        now.isoformat()
    )

    # --------------------------------------------
    # Only after every market price has been
    # successfully retrieved do we persist.
    # --------------------------------------------

    with database.connection() as conn:

        conn.execute(
            """
            INSERT INTO
                valuation_snapshots (

                bucket_utc,
                captured_at_utc,
                cash_usdc,
                market_value_usdc,
                nav_usdc,
                shares_outstanding,
                nav_per_share_usdc,
                index_level,
                feed_cutoff_utc,
                valuation_source
            )
            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                bucket_utc,
                captured_at_utc,
                str(
                    valuation.cash
                ),
                str(
                    valuation.market_value
                ),
                str(
                    valuation.nav
                ),
                str(
                    valuation.shares
                ),
                str(
                    valuation.nav_per_share
                ),
                str(
                    feed.index_level
                ),
                feed.cutoff_utc,
                "BINANCE_DEMO_MID",
            ),
        )

        snapshot_id = (
            conn.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]
        )

    print("=" * 80)
    print(
        "ETF INDICATIVE VALUATION SNAPSHOT"
    )
    print("=" * 80)

    print()

    print(
        f"Snapshot ID        : "
        f"{snapshot_id}"
    )

    print(
        f"Bucket UTC         : "
        f"{bucket_utc}"
    )

    print(
        f"Captured UTC       : "
        f"{captured_at_utc}"
    )

    print(
        f"ETF cash           : "
        f"{valuation.cash:.8f} "
        f"{base_currency}"
    )

    print(
        f"Market value       : "
        f"{valuation.market_value:.8f} "
        f"{base_currency}"
    )

    print(
        f"NAV                : "
        f"{valuation.nav:.8f} "
        f"{base_currency}"
    )

    print(
        f"Shares             : "
        f"{valuation.shares}"
    )

    print(
        f"NAV/share          : "
        f"{valuation.nav_per_share:.8f} "
        f"{base_currency}"
    )

    print(
        f"Index level        : "
        f"{feed.index_level}"
    )

    print()

    print(
        "Valuation source   : "
        "BINANCE_DEMO_MID"
    )

    print(
        "No Binance order was sent."
    )


if __name__ == "__main__":
    main()
