from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sqlite3


STATUS_PENDING = "PENDING_PHYSICAL_FUNDS"
STATUS_ACCEPTED = "ACCEPTED_PENDING_INVESTMENT"
STATUS_INVESTING = "INVESTMENT_IN_PROGRESS"
STATUS_RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
STATUS_COMPLETED = "COMPLETED"


class ContributionRepository:

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def ensure_schema(
        self,
        conn: sqlite3.Connection,
    ) -> None:

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS
            cash_contributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                period_id TEXT NOT NULL UNIQUE,

                scheduled_at_utc TEXT NOT NULL,

                currency TEXT NOT NULL,

                expected_amount TEXT NOT NULL,

                detected_amount TEXT,

                accepted_amount TEXT,

                feed_cutoff_utc TEXT NOT NULL,

                nav_before_usdc TEXT,

                nav_per_share_before_usdc TEXT,

                shares_before TEXT,

                shares_issued TEXT,

                shares_after TEXT,

                status TEXT NOT NULL,

                created_at_utc TEXT NOT NULL,

                updated_at_utc TEXT NOT NULL,

                accepted_at_utc TEXT,

                completed_at_utc TEXT,

                notes TEXT
            )
            """
        )

    def get_by_period(
        self,
        conn: sqlite3.Connection,
        period_id: str,
    ):

        return conn.execute(
            """
            SELECT *
            FROM cash_contributions
            WHERE period_id = ?
            """,
            (period_id,),
        ).fetchone()

    def record_pending(
        self,
        conn: sqlite3.Connection,
        *,
        period_id: str,
        scheduled_at_utc: str,
        currency: str,
        expected_amount: Decimal,
        detected_amount: Decimal,
        feed_cutoff_utc: str,
        notes: str | None = None,
    ) -> None:

        self.ensure_schema(conn)

        existing = self.get_by_period(
            conn,
            period_id,
        )

        if (
            existing is not None
            and existing["status"]
            in {
                STATUS_ACCEPTED,
                STATUS_INVESTING,
                STATUS_RECOVERY_REQUIRED,
                STATUS_COMPLETED,
            }
        ):
            return

        timestamp = self._utc_now()

        if existing is None:

            conn.execute(
                """
                INSERT INTO cash_contributions (
                    period_id,
                    scheduled_at_utc,
                    currency,
                    expected_amount,
                    detected_amount,
                    accepted_amount,
                    feed_cutoff_utc,
                    status,
                    created_at_utc,
                    updated_at_utc,
                    notes
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    period_id,
                    scheduled_at_utc,
                    currency,
                    str(expected_amount),
                    str(detected_amount),
                    None,
                    feed_cutoff_utc,
                    STATUS_PENDING,
                    timestamp,
                    timestamp,
                    notes,
                ),
            )

        else:

            conn.execute(
                """
                UPDATE cash_contributions
                SET
                    detected_amount = ?,
                    updated_at_utc = ?,
                    notes = ?
                WHERE period_id = ?
                """,
                (
                    str(detected_amount),
                    timestamp,
                    notes,
                    period_id,
                ),
            )

    def accept_contribution(
        self,
        conn: sqlite3.Connection,
        *,
        period_id: str,
        scheduled_at_utc: str,
        currency: str,
        amount: Decimal,
        detected_amount: Decimal,
        feed_cutoff_utc: str,
        cash_before: Decimal,
        market_value_before: Decimal,
        nav_before: Decimal,
        nav_per_share_before: Decimal,
        shares_before: Decimal,
        index_level: Decimal | None,
    ) -> dict:

        self.ensure_schema(conn)

        existing = self.get_by_period(
            conn,
            period_id,
        )

        if (
            existing is not None
            and existing["status"]
            in {
                STATUS_ACCEPTED,
                STATUS_INVESTING,
                STATUS_RECOVERY_REQUIRED,
                STATUS_COMPLETED,
            }
        ):
            raise RuntimeError(
                "Contribution period has "
                "already been accepted: "
                f"{period_id}"
            )

        if amount <= 0:
            raise ValueError(
                "Contribution amount must "
                "be positive."
            )

        if nav_before <= 0:
            raise RuntimeError(
                "NAV before contribution "
                "must be positive."
            )

        if nav_per_share_before <= 0:
            raise RuntimeError(
                "NAV/share before contribution "
                "must be positive."
            )

        if shares_before <= 0:
            raise RuntimeError(
                "shares_outstanding must "
                "be positive."
            )

        shares_issued = (
            amount
            / nav_per_share_before
        )

        shares_after = (
            shares_before
            + shares_issued
        )

        cash_after = (
            cash_before
            + amount
        )

        nav_after = (
            nav_before
            + amount
        )

        nav_per_share_after = (
            nav_after
            / shares_after
        )

        timestamp = self._utc_now()

        reference = (
            "IDXETF_C"
            + period_id.replace(
                "-",
                "",
            )
        )

        # -------------------------------------------------
        # Cash ownership
        # -------------------------------------------------

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
                currency,
                str(amount),
                "CAPITAL_CONTRIBUTION",
                reference,
                (
                    "Weekly ETF cash "
                    f"contribution {period_id}"
                ),
            ),
        )

        # -------------------------------------------------
        # Share issuance
        # -------------------------------------------------

        cursor = conn.execute(
            """
            UPDATE meta
            SET value = ?
            WHERE key = 'shares_outstanding'
            """,
            (
                str(shares_after),
            ),
        )

        if cursor.rowcount != 1:
            raise RuntimeError(
                "shares_outstanding metadata "
                "was not found."
            )

        # -------------------------------------------------
        # Post-contribution NAV snapshot
        #
        # Market value is unchanged because no trades
        # occur during contribution acceptance.
        # -------------------------------------------------

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
                str(cash_after),
                str(market_value_before),
                str(nav_after),
                str(shares_after),
                str(nav_per_share_after),
                (
                    None
                    if index_level is None
                    else str(index_level)
                ),
                None,
            ),
        )

        # -------------------------------------------------
        # Contribution lifecycle
        # -------------------------------------------------

        if existing is None:

            conn.execute(
                """
                INSERT INTO cash_contributions (
                    period_id,
                    scheduled_at_utc,
                    currency,
                    expected_amount,
                    detected_amount,
                    accepted_amount,
                    feed_cutoff_utc,
                    nav_before_usdc,
                    nav_per_share_before_usdc,
                    shares_before,
                    shares_issued,
                    shares_after,
                    status,
                    created_at_utc,
                    updated_at_utc,
                    accepted_at_utc,
                    notes
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    period_id,
                    scheduled_at_utc,
                    currency,
                    str(amount),
                    str(detected_amount),
                    str(amount),
                    feed_cutoff_utc,
                    str(nav_before),
                    str(nav_per_share_before),
                    str(shares_before),
                    str(shares_issued),
                    str(shares_after),
                    STATUS_ACCEPTED,
                    timestamp,
                    timestamp,
                    timestamp,
                    (
                        "Contribution accepted; "
                        "investment still pending."
                    ),
                ),
            )

        else:

            conn.execute(
                """
                UPDATE cash_contributions
                SET
                    detected_amount = ?,
                    accepted_amount = ?,
                    nav_before_usdc = ?,
                    nav_per_share_before_usdc = ?,
                    shares_before = ?,
                    shares_issued = ?,
                    shares_after = ?,
                    status = ?,
                    updated_at_utc = ?,
                    accepted_at_utc = ?,
                    notes = ?
                WHERE period_id = ?
                """,
                (
                    str(detected_amount),
                    str(amount),
                    str(nav_before),
                    str(nav_per_share_before),
                    str(shares_before),
                    str(shares_issued),
                    str(shares_after),
                    STATUS_ACCEPTED,
                    timestamp,
                    timestamp,
                    (
                        "Contribution accepted; "
                        "investment still pending."
                    ),
                    period_id,
                ),
            )

        return {
            "period_id": period_id,
            "amount": amount,
            "cash_before": cash_before,
            "cash_after": cash_after,
            "market_value_before":
                market_value_before,
            "nav_before": nav_before,
            "nav_after": nav_after,
            "nav_per_share_before":
                nav_per_share_before,
            "nav_per_share_after":
                nav_per_share_after,
            "shares_before": shares_before,
            "shares_issued": shares_issued,
            "shares_after": shares_after,
            "status": STATUS_ACCEPTED,
        }


    def mark_investment_in_progress(
        self,
        conn: sqlite3.Connection,
        *,
        contribution_id: int,
    ) -> None:

        row = conn.execute(
            """
            SELECT status
            FROM cash_contributions
            WHERE id = ?
            """,
            (contribution_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Contribution not found."
            )

        status = row["status"]

        if status == STATUS_INVESTING:
            return

        if status != STATUS_ACCEPTED:
            raise RuntimeError(
                "Contribution cannot enter "
                "investment state from "
                f"{status}."
            )

        conn.execute(
            """
            UPDATE cash_contributions
            SET
                status = ?,
                updated_at_utc = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                STATUS_INVESTING,
                self._utc_now(),
                (
                    "Contribution investment "
                    "execution started."
                ),
                contribution_id,
            ),
        )

    def mark_recovery_required(
        self,
        conn: sqlite3.Connection,
        *,
        contribution_id: int,
        notes: str,
    ) -> None:

        row = conn.execute(
            """
            SELECT status
            FROM cash_contributions
            WHERE id = ?
            """,
            (contribution_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Contribution not found."
            )

        if row["status"] == STATUS_COMPLETED:
            raise RuntimeError(
                "Completed contribution cannot "
                "enter recovery state."
            )

        conn.execute(
            """
            UPDATE cash_contributions
            SET
                status = ?,
                updated_at_utc = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                STATUS_RECOVERY_REQUIRED,
                self._utc_now(),
                notes,
                contribution_id,
            ),
        )

    def mark_completed(
        self,
        conn: sqlite3.Connection,
        *,
        contribution_id: int,
        notes: str | None = None,
    ) -> None:

        row = conn.execute(
            """
            SELECT status
            FROM cash_contributions
            WHERE id = ?
            """,
            (contribution_id,),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                "Contribution not found."
            )

        if row["status"] == STATUS_COMPLETED:
            return

        if row["status"] != STATUS_INVESTING:
            raise RuntimeError(
                "Contribution cannot complete "
                "from state "
                f"{row['status']}."
            )

        timestamp = self._utc_now()

        conn.execute(
            """
            UPDATE cash_contributions
            SET
                status = ?,
                updated_at_utc = ?,
                completed_at_utc = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                STATUS_COMPLETED,
                timestamp,
                timestamp,
                notes,
                contribution_id,
            ),
        )
