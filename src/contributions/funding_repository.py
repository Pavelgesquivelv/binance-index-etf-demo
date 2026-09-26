from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sqlite3


ZERO = Decimal("0")

EVENT_INITIAL_FUNDING = "INITIAL_FUNDING"
EVENT_CONTRIBUTION_ACCEPTED = (
    "CONTRIBUTION_ACCEPTED"
)


class ContributionFundingRepository:

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def ensure_schema(
        self,
        conn: sqlite3.Connection,
    ) -> None:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS
            contribution_funding_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                timestamp_utc TEXT NOT NULL,
                currency TEXT NOT NULL,

                amount TEXT NOT NULL,
                event_type TEXT NOT NULL,

                reference TEXT NOT NULL UNIQUE,
                notes TEXT
            );

            CREATE INDEX IF NOT EXISTS
                ix_contribution_funding_currency
                ON contribution_funding_ledger(
                    currency,
                    id
                );

            CREATE TRIGGER IF NOT EXISTS
                tr_contribution_funding_no_update
            BEFORE UPDATE ON
                contribution_funding_ledger
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'contribution_funding_ledger is append-only'
                );
            END;

            CREATE TRIGGER IF NOT EXISTS
                tr_contribution_funding_no_delete
            BEFORE DELETE ON
                contribution_funding_ledger
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'contribution_funding_ledger is append-only'
                );
            END;
            """
        )

    def get_balance(
        self,
        conn: sqlite3.Connection,
        currency: str,
    ) -> Decimal:

        currency = currency.upper()

        rows = conn.execute(
            """
            SELECT amount
            FROM contribution_funding_ledger
            WHERE currency = ?
            ORDER BY id
            """,
            (currency,),
        ).fetchall()

        balance = sum(
            (
                Decimal(row["amount"])
                for row in rows
            ),
            ZERO,
        )

        if balance < ZERO:
            raise RuntimeError(
                "Contribution funding ledger "
                "balance cannot be negative: "
                f"{currency}={balance}"
            )

        return balance

    def get_entries(
        self,
        conn: sqlite3.Connection,
        currency: str,
    ):

        return conn.execute(
            """
            SELECT *
            FROM contribution_funding_ledger
            WHERE currency = ?
            ORDER BY id
            """,
            (currency.upper(),),
        ).fetchall()

    def initialize_funding(
        self,
        conn: sqlite3.Connection,
        *,
        currency: str,
        amount: Decimal,
        notes: str | None = None,
    ) -> Decimal:

        currency = currency.upper()

        if amount <= ZERO:
            raise ValueError(
                "Initial contribution funding "
                "must be positive."
            )

        existing = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM contribution_funding_ledger
            WHERE currency = ?
            """,
            (currency,),
        ).fetchone()["n"]

        if existing:
            raise RuntimeError(
                "Contribution funding ledger "
                "is already initialized for "
                f"{currency}."
            )

        reference = (
            f"INITIAL_FUNDING:{currency}"
        )

        conn.execute(
            """
            INSERT INTO
                contribution_funding_ledger (
                    timestamp_utc,
                    currency,
                    amount,
                    event_type,
                    reference,
                    notes
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._utc_now(),
                currency,
                str(amount),
                EVENT_INITIAL_FUNDING,
                reference,
                notes,
            ),
        )

        return amount

    def consume_for_contribution(
        self,
        conn: sqlite3.Connection,
        *,
        currency: str,
        amount: Decimal,
        period_id: str,
        notes: str | None = None,
    ) -> Decimal:

        currency = currency.upper()

        if amount <= ZERO:
            raise ValueError(
                "Funding consumption amount "
                "must be positive."
            )

        balance_before = self.get_balance(
            conn,
            currency,
        )

        if balance_before < amount:
            raise RuntimeError(
                "Insufficient contribution "
                "funding reserve: "
                f"available={balance_before}, "
                f"required={amount} "
                f"{currency}"
            )

        reference = (
            "CONTRIBUTION:"
            f"{period_id}:"
            f"{currency}"
        )

        existing = conn.execute(
            """
            SELECT id
            FROM contribution_funding_ledger
            WHERE reference = ?
            """,
            (reference,),
        ).fetchone()

        if existing is not None:
            raise RuntimeError(
                "Contribution funding was "
                "already consumed for "
                f"{period_id}."
            )

        conn.execute(
            """
            INSERT INTO
                contribution_funding_ledger (
                    timestamp_utc,
                    currency,
                    amount,
                    event_type,
                    reference,
                    notes
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self._utc_now(),
                currency,
                str(-amount),
                EVENT_CONTRIBUTION_ACCEPTED,
                reference,
                notes,
            ),
        )

        return (
            balance_before
            - amount
        )
