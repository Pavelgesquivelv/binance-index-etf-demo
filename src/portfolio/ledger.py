from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from src.storage.database import Database


class PortfolioLedger:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def initialize_fund(
        self,
        *,
        fund_name: str,
        base_currency: str,
        initial_capital: Decimal,
        shares_outstanding: Decimal,
        order_prefix: str,
    ) -> bool:
        """
        Initializes the ETF once.

        Returns:
            True  -> fund created
            False -> fund was already initialized
        """

        if initial_capital <= 0:
            raise ValueError(
                "initial_capital must be positive."
            )

        if shares_outstanding <= 0:
            raise ValueError(
                "shares_outstanding must be positive."
            )

        timestamp = self._utc_now()

        initial_nav_per_share = (
            initial_capital / shares_outstanding
        )

        with self.database.connection() as conn:
            existing = conn.execute(
                """
                SELECT value
                FROM meta
                WHERE key = 'initialized'
                """
            ).fetchone()

            if existing is not None:
                return False

            metadata = {
                "initialized": "1",
                "fund_name": fund_name,
                "base_currency": base_currency,
                "initial_capital": str(initial_capital),
                "shares_outstanding": str(
                    shares_outstanding
                ),
                "initial_nav_per_share": str(
                    initial_nav_per_share
                ),
                "order_prefix": order_prefix,
                "initialized_at_utc": timestamp,
            }

            conn.executemany(
                """
                INSERT INTO meta (key, value)
                VALUES (?, ?)
                """,
                metadata.items(),
            )

            conn.execute(
                """
                INSERT INTO cash_ledger (
                    timestamp_utc,
                    asset,
                    amount,
                    event_type,
                    reference,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    base_currency,
                    str(initial_capital),
                    "CAPITAL_CONTRIBUTION",
                    "FUND_INITIALIZATION",
                    "Initial ETF demo capital",
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    str(initial_capital),
                    "0",
                    str(initial_capital),
                    str(shares_outstanding),
                    str(initial_nav_per_share),
                    None,
                    None,
                ),
            )

        return True

    def get_meta(
        self,
        key: str,
    ) -> str | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT value
                FROM meta
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

        if row is None:
            return None

        return row["value"]

    def get_metadata(self) -> dict[str, str]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT key, value
                FROM meta
                ORDER BY key
                """
            ).fetchall()

        return {
            row["key"]: row["value"]
            for row in rows
        }

    def get_cash_balance(
        self,
        asset: str,
    ) -> Decimal:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT amount
                FROM cash_ledger
                WHERE asset = ?
                ORDER BY id
                """,
                (asset,),
            ).fetchall()

        balance = Decimal("0")

        for row in rows:
            balance += Decimal(row["amount"])

        return balance

    def get_positions(
        self,
    ) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    asset,
                    quantity,
                    average_cost_usdc,
                    updated_at_utc
                FROM positions
                ORDER BY asset
                """
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def get_latest_nav(
        self,
    ) -> dict[str, Any] | None:
        with self.database.connection() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM nav_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return dict(row)
