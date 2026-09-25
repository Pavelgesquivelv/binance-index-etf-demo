from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
)


ZERO = Decimal("0")


def _decimal(
    value: Any,
    default: str = "0",
) -> Decimal:

    if value is None:
        return Decimal(default)

    return Decimal(str(value))


def _enabled(name: str) -> bool:

    return (
        os.getenv(name, "false")
        .strip()
        .lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def _connect_read_only(
    database_path: Path,
) -> sqlite3.Connection:

    uri = (
        database_path
        .resolve()
        .as_uri()
        + "?mode=ro"
    )

    conn = sqlite3.connect(
        uri,
        uri=True,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    return conn


def _table_exists(
    conn: sqlite3.Connection,
    table: str,
) -> bool:

    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table'
          AND name=?
        """,
        (table,),
    ).fetchone()

    return row is not None


def _cash_balance(
    conn: sqlite3.Connection,
    asset: str,
) -> Decimal:

    rows = conn.execute(
        """
        SELECT amount
        FROM cash_ledger
        WHERE asset = ?
        ORDER BY id
        """,
        (asset,),
    ).fetchall()

    return sum(
        (
            _decimal(row["amount"])
            for row in rows
        ),
        ZERO,
    )


def _free_balances(
    account: dict,
) -> dict[str, Decimal]:

    return {
        row["asset"].upper():
            _decimal(row["free"])
        for row in account.get(
            "balances",
            [],
        )
    }


def load_dashboard_snapshot(
    root: Path,
) -> dict[str, Any]:

    root = root.resolve()

    load_dotenv(
        root / ".env",
        override=False,
    )

    with (
        root
        / "config"
        / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:

        config = yaml.safe_load(file)

    base_currency = (
        config["fund"]["base_currency"]
        .upper()
    )

    database_path = (
        root
        / config["storage"]["database"]
    )

    feed = PortfolioFeedLoader(
        root
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    target_weights = {
        item.asset:
            _decimal(
                item.target_weight_pct
            )
        for item in feed.positions
    }

    with _connect_read_only(
        database_path
    ) as conn:

        metadata = {
            row["key"]: row["value"]
            for row in conn.execute(
                """
                SELECT key, value
                FROM meta
                ORDER BY key
                """
            ).fetchall()
        }

        cash = _cash_balance(
            conn,
            base_currency,
        )

        positions = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    asset,
                    quantity,
                    average_cost_usdc,
                    updated_at_utc
                FROM positions
                WHERE CAST(quantity AS REAL)
                      <> 0
                ORDER BY asset
                """
            ).fetchall()
        ]

        nav_history = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    id,
                    timestamp_utc,
                    cash_usdc,
                    market_value_usdc,
                    nav_usdc,
                    shares_outstanding,
                    nav_per_share_usdc,
                    index_level,
                    tracking_difference
                FROM nav_snapshots
                ORDER BY id
                """
            ).fetchall()
        ]

        if _table_exists(
            conn,
            "valuation_snapshots",
        ):

            valuation_history = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        id,
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
                    FROM valuation_snapshots
                    ORDER BY captured_at_utc
                    """
                ).fetchall()
            ]

        else:

            valuation_history = []

        rebalances = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    id,
                    started_at_utc,
                    completed_at_utc,
                    cutoff_utc,
                    index_level,
                    nav_before_usdc,
                    status,
                    notes
                FROM rebalance_runs
                ORDER BY id DESC
                """
            ).fetchall()
        ]

        completed_current = (
            conn.execute(
                """
                SELECT
                    id,
                    completed_at_utc
                FROM rebalance_runs
                WHERE cutoff_utc = ?
                  AND status = 'COMPLETED'
                ORDER BY id DESC
                LIMIT 1
                """,
                (feed.cutoff_utc,),
            ).fetchone()
        )

        recoverable_orders = int(
            conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM orders o
                JOIN order_lifecycle l
                  ON l.order_id = o.id
                WHERE l.local_status
                      <> 'ACCOUNTED'
                """
            ).fetchone()["n"]
        )

        if _table_exists(
            conn,
            "cash_contributions",
        ):

            contributions = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT *
                    FROM cash_contributions
                    ORDER BY id DESC
                    """
                ).fetchall()
            ]

        else:
            contributions = []

        orders = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    o.id,

                    CASE
                        WHEN o.contribution_id
                             IS NOT NULL
                        THEN 'CONTRIBUTION'
                        ELSE 'REBALANCE'
                    END AS owner_type,

                    o.rebalance_run_id,
                    o.contribution_id,

                    o.created_at_utc,
                    o.client_order_id,
                    o.symbol,
                    o.asset,
                    o.side,

                    o.requested_quantity,
                    o.requested_quote_quantity,

                    o.exchange_order_id,
                    o.exchange_status,
                    o.executed_quantity,
                    o.cumulative_quote_quantity,

                    l.local_status,
                    l.updated_at_utc,
                    l.last_error,

                    b.mid_price AS benchmark_mid,
                    b.spread_bps,

                    (
                        SELECT COUNT(*)
                        FROM fills f
                        WHERE f.order_id = o.id
                    ) AS fill_count

                FROM orders o

                JOIN order_lifecycle l
                  ON l.order_id = o.id

                LEFT JOIN execution_benchmarks b
                  ON b.order_id = o.id

                ORDER BY o.id DESC
                """
            ).fetchall()
        ]

        fee_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT
                    asset,
                    SUM(
                        CAST(amount AS REAL)
                    ) AS amount
                FROM fee_ledger
                GROUP BY asset
                ORDER BY asset
                """
            ).fetchall()
        ]

    shares = _decimal(
        metadata.get(
            "shares_outstanding",
            "0",
        )
    )

    # --------------------------------------------------
    # Live Binance state.
    # GET requests only.
    # --------------------------------------------------

    live_error = None
    account = None

    books: dict[
        str,
        dict[str, Decimal],
    ] = {}

    try:

        client = BinanceDemoClient()

        account = client.get_account()

        assets = sorted(
            set(target_weights)
            | {
                row["asset"]
                for row in positions
            }
        )

        for asset in assets:

            symbol = (
                f"{asset}{base_currency}"
            )

            ticker = (
                client.get_book_ticker(
                    symbol
                )
            )

            bid = _decimal(
                ticker["bidPrice"]
            )

            ask = _decimal(
                ticker["askPrice"]
            )

            books[asset] = {
                "bid": bid,
                "ask": ask,
                "mid": (
                    bid + ask
                ) / Decimal("2"),
            }

    except Exception as exc:

        live_error = str(exc)

    # --------------------------------------------------
    # Indicative NAV from ETF ledger quantities and
    # live Binance mid prices.
    # --------------------------------------------------

    portfolio = []

    live_market_value = ZERO

    for row in positions:

        asset = row["asset"]

        quantity = _decimal(
            row["quantity"]
        )

        book = books.get(asset)

        mid = (
            book["mid"]
            if book is not None
            else None
        )

        market_value = (
            quantity * mid
            if mid is not None
            else None
        )

        if market_value is not None:
            live_market_value += (
                market_value
            )

        portfolio.append(
            {
                "asset": asset,
                "quantity": quantity,
                "average_cost_usdc":
                    _decimal(
                        row[
                            "average_cost_usdc"
                        ]
                    ),
                "mid_price_usdc": mid,
                "market_value_usdc":
                    market_value,
                "target_weight_pct":
                    target_weights.get(
                        asset,
                        ZERO,
                    ),
                "updated_at_utc":
                    row["updated_at_utc"],
            }
        )

    live_nav = (
        cash + live_market_value
        if live_error is None
        else None
    )

    live_nav_per_share = (
        live_nav / shares
        if (
            live_nav is not None
            and shares > ZERO
        )
        else None
    )

    for row in portfolio:

        market_value = (
            row["market_value_usdc"]
        )

        if (
            market_value is not None
            and live_nav is not None
            and live_nav > ZERO
        ):

            current_weight = (
                market_value
                / live_nav
                * Decimal("100")
            )

        else:
            current_weight = None

        row["current_weight_pct"] = (
            current_weight
        )

        row["weight_drift_pct"] = (
            current_weight
            - row["target_weight_pct"]
            if current_weight is not None
            else None
        )

    # --------------------------------------------------
    # Physical backing.
    #
    # ETF ownership comes from SQLite.
    # Binance balances are used only to verify
    # that the owned inventory physically exists.
    # --------------------------------------------------

    physical_backing = []

    if account is not None:

        free = _free_balances(
            account
        )

        shared_bnb_reserve = (
            _decimal(
                config.get(
                    "account_isolation",
                    {},
                ).get(
                    "shared_bnb_fee_reserve",
                    "0",
                )
            )
        )

        requirements = {
            base_currency: cash,
        }

        for row in positions:

            requirements[
                row["asset"]
            ] = _decimal(
                row["quantity"]
            )

        if (
            shared_bnb_reserve
            > ZERO
        ):

            requirements["BNB"] = (
                requirements.get(
                    "BNB",
                    ZERO,
                )
                + shared_bnb_reserve
            )

        for asset in sorted(
            requirements
        ):

            required = (
                requirements[asset]
            )

            exchange_free = (
                free.get(
                    asset,
                    ZERO,
                )
            )

            surplus = (
                exchange_free
                - required
            )

            physical_backing.append(
                {
                    "asset": asset,
                    "required": required,
                    "exchange_free":
                        exchange_free,
                    "surplus": surplus,
                    "is_backed":
                        surplus >= ZERO,
                }
            )

    backing_ok = (
        bool(physical_backing)
        and all(
            row["is_backed"]
            for row in physical_backing
        )
    )

    # --------------------------------------------------
    # Feed age is informational.
    # A historical feed may legitimately be old once
    # its cutoff is already COMPLETED.
    # --------------------------------------------------

    cutoff_dt = (
        datetime.fromisoformat(
            feed.cutoff_utc
        )
    )

    feed_age_hours = (
        (
            datetime.now(
                timezone.utc
            )
            - cutoff_dt
        ).total_seconds()
        / 3600
    )

    latest_contribution = (
        contributions[0]
        if contributions
        else None
    )

    latest_valuation_at_utc = None
    valuation_age_minutes = None

    if valuation_history:

        latest_valuation_at_utc = (
            valuation_history[-1][
                "captured_at_utc"
            ]
        )

        latest_valuation_dt = (
            datetime.fromisoformat(
                latest_valuation_at_utc
            )
        )

        if (
            latest_valuation_dt.tzinfo
            is None
        ):
            latest_valuation_dt = (
                latest_valuation_dt.replace(
                    tzinfo=timezone.utc
                )
            )

        valuation_age_minutes = (
            (
                datetime.now(
                    timezone.utc
                )
                - latest_valuation_dt
            ).total_seconds()
            / 60
        )

    flags = {
        "BINANCE_TRADING_ENABLED":
            _enabled(
                "BINANCE_TRADING_ENABLED"
            ),
        "ETF_WEEKLY_AUTOMATION_ENABLED":
            _enabled(
                "ETF_WEEKLY_AUTOMATION_ENABLED"
            ),
        "ETF_CONTRIBUTION_EXECUTION_ENABLED":
            _enabled(
                "ETF_CONTRIBUTION_EXECUTION_ENABLED"
            ),
    }

    return {
        "base_currency":
            base_currency,

        "metadata":
            metadata,

        "cash":
            cash,

        "shares":
            shares,

        "feed_cutoff_utc":
            feed.cutoff_utc,

        "index_level":
            feed.index_level,

        "feed_age_hours":
            feed_age_hours,

        "current_feed_processed":
            completed_current
            is not None,

        "completed_run_id":
            (
                int(
                    completed_current["id"]
                )
                if completed_current
                is not None
                else None
            ),

        "completed_at_utc":
            (
                completed_current[
                    "completed_at_utc"
                ]
                if completed_current
                is not None
                else None
            ),

        "recoverable_orders":
            recoverable_orders,

        "latest_contribution":
            latest_contribution,

        "portfolio":
            portfolio,

        "nav_history":
            nav_history,

        "rebalances":
            rebalances,

        "contributions":
            contributions,

        "orders":
            orders,

        "fees":
            fee_rows,

        "live_market_value":
            live_market_value,

        "live_nav":
            live_nav,

        "live_nav_per_share":
            live_nav_per_share,

        "physical_backing":
            physical_backing,

        "physical_backing_ok":
            backing_ok,

        "flags":
            flags,

        "live_error":
            live_error,

        "valuation_history":
            valuation_history,

        "latest_valuation_at_utc":
            latest_valuation_at_utc,

        "valuation_age_minutes":
            valuation_age_minutes,

        "schedule":
            config.get(
                "cash_contributions",
                {},
            ).get(
                "schedule",
                {},
            ),
    }
