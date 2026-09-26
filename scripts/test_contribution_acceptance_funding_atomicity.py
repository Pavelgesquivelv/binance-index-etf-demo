from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_repository import (
    ContributionRepository,
    STATUS_ACCEPTED,
)
from src.contributions.funding_repository import (
    ContributionFundingRepository,
)
from src.storage.database import (
    Database,
)


ZERO = Decimal("0")
CURRENCY = "USDC"
PERIOD = "2026-W40"
AMOUNT = Decimal("200")


def cash_balance(
    conn,
) -> Decimal:

    return sum(
        (
            Decimal(row["amount"])
            for row in conn.execute(
                """
                SELECT amount
                FROM cash_ledger
                WHERE asset = ?
                ORDER BY id
                """,
                (CURRENCY,),
            ).fetchall()
        ),
        ZERO,
    )


with tempfile.TemporaryDirectory() as tmp:

    database = Database(
        str(
            Path(tmp)
            / "acceptance_atomicity.db"
        )
    )

    database.initialize_schema()

    contribution_repository = (
        ContributionRepository()
    )

    funding_repository = (
        ContributionFundingRepository()
    )

    with database.connection() as conn:

        contribution_repository\
            .ensure_schema(conn)

        funding_repository\
            .ensure_schema(conn)

        conn.execute(
            """
            INSERT OR REPLACE INTO meta (
                key,
                value
            )
            VALUES (?, ?)
            """,
            (
                "shares_outstanding",
                "50",
            ),
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
                "2026-09-26T00:00:00+00:00",
                CURRENCY,
                "5000",
                "TEST_SEED",
                "TEST_SEED_CASH",
                "Test-only cash seed.",
            ),
        )

        funding_repository\
            .initialize_funding(
                conn,
                currency=CURRENCY,
                amount=Decimal("2000"),
                notes="Test initial reserve.",
            )

    # ==================================================
    # 1. Failure after funding consumption must roll
    #    back BOTH funding and contribution accounting.
    # ==================================================

    failure_detected = False

    try:

        with database.connection() as conn:

            funding_repository\
                .consume_for_contribution(
                    conn,
                    currency=CURRENCY,
                    amount=AMOUNT,
                    period_id=PERIOD,
                    notes="Rollback test.",
                )

            # Deliberately invalid shares_before.
            # accept_contribution must raise after the
            # funding debit, forcing the entire caller
            # transaction to roll back.
            contribution_repository\
                .accept_contribution(
                    conn,
                    period_id=PERIOD,
                    scheduled_at_utc=(
                        "2026-09-28T15:00:00+00:00"
                    ),
                    currency=CURRENCY,
                    amount=AMOUNT,
                    detected_amount=AMOUNT,
                    feed_cutoff_utc=(
                        "2026-08-31T13:00:00+00:00"
                    ),
                    cash_before=Decimal("5000"),
                    market_value_before=ZERO,
                    nav_before=Decimal("5000"),
                    nav_per_share_before=(
                        Decimal("100")
                    ),
                    shares_before=ZERO,
                    index_level=Decimal(
                        "56.41415870095715"
                    ),
                )

    except RuntimeError:
        failure_detected = True

    assert failure_detected

    with database.connection() as conn:

        assert (
            funding_repository.get_balance(
                conn,
                CURRENCY,
            )
            == Decimal("2000")
        )

        assert (
            cash_balance(conn)
            == Decimal("5000")
        )

        shares = conn.execute(
            """
            SELECT value
            FROM meta
            WHERE key = 'shares_outstanding'
            """
        ).fetchone()

        assert (
            Decimal(shares["value"])
            == Decimal("50")
        )

        contribution = (
            contribution_repository
            .get_by_period(
                conn,
                PERIOD,
            )
        )

        assert contribution is None

        rows = (
            funding_repository.get_entries(
                conn,
                CURRENCY,
            )
        )

        assert len(rows) == 1


    # ==================================================
    # 2. Successful acceptance transfers ownership:
    #
    # funding 2000 -> 1800
    # ETF cash 5000 -> 5200
    # shares 50 -> 52
    #
    # Combined owned USDC remains 7000.
    # ==================================================

    with database.connection() as conn:

        funding_before = (
            funding_repository.get_balance(
                conn,
                CURRENCY,
            )
        )

        cash_before = cash_balance(
            conn
        )

        funding_repository\
            .consume_for_contribution(
                conn,
                currency=CURRENCY,
                amount=AMOUNT,
                period_id=PERIOD,
                notes=(
                    "Successful atomic "
                    "acceptance test."
                ),
            )

        result = (
            contribution_repository
            .accept_contribution(
                conn,
                period_id=PERIOD,
                scheduled_at_utc=(
                    "2026-09-28T15:00:00+00:00"
                ),
                currency=CURRENCY,
                amount=AMOUNT,
                detected_amount=AMOUNT,
                feed_cutoff_utc=(
                    "2026-08-31T13:00:00+00:00"
                ),
                cash_before=cash_before,
                market_value_before=ZERO,
                nav_before=Decimal("5000"),
                nav_per_share_before=(
                    Decimal("100")
                ),
                shares_before=Decimal("50"),
                index_level=Decimal(
                    "56.41415870095715"
                ),
            )
        )

        funding_after = (
            funding_repository.get_balance(
                conn,
                CURRENCY,
            )
        )

        cash_after = cash_balance(
            conn
        )

        assert (
            funding_after
            == Decimal("1800")
        )

        assert (
            cash_after
            == Decimal("5200")
        )

        assert (
            cash_before
            + funding_before
            == cash_after
            + funding_after
        )

        assert (
            result["shares_after"]
            == Decimal("52")
        )

    with database.connection() as conn:

        contribution = (
            contribution_repository
            .get_by_period(
                conn,
                PERIOD,
            )
        )

        assert contribution is not None

        assert (
            contribution["status"]
            == STATUS_ACCEPTED
        )

        assert (
            Decimal(
                contribution[
                    "accepted_amount"
                ]
            )
            == AMOUNT
        )

        assert (
            Decimal(
                contribution[
                    "detected_amount"
                ]
            )
            == AMOUNT
        )

        assert (
            funding_repository.get_balance(
                conn,
                CURRENCY,
            )
            == Decimal("1800")
        )

        assert (
            cash_balance(conn)
            == Decimal("5200")
        )

        funding_rows = (
            funding_repository.get_entries(
                conn,
                CURRENCY,
            )
        )

        assert len(funding_rows) == 2


print(
    "Contribution acceptance funding atomicity: OK"
)

print(
    "Failed acceptance funding rollback : OK"
)

print(
    "Failed acceptance ETF rollback     : OK"
)

print(
    "Initial funding                    : 2000 USDC"
)

print(
    "Accepted contribution              : 200 USDC"
)

print(
    "Remaining funding                  : 1800 USDC"
)

print(
    "ETF cash                           : 5200 USDC"
)

print(
    "Ownership conservation             : OK"
)

print(
    "Accepted detected_amount           : 200 USDC"
)
