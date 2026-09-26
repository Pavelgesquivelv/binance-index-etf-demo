from __future__ import annotations

from decimal import Decimal
import sqlite3


ZERO = Decimal("0")


def get_contribution_funding_balance(
    conn: sqlite3.Connection,
    currency: str,
) -> Decimal:
    """
    Read the existing contribution funding ledger.

    This function is intentionally read-only:
    - no CREATE TABLE
    - no migrations
    - no INSERT / UPDATE
    """

    currency = currency.upper()

    table = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'contribution_funding_ledger'
        """
    ).fetchone()

    if table is None:
        raise RuntimeError(
            "contribution_funding_ledger "
            "schema is missing."
        )

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
            "Contribution funding balance "
            "cannot be negative: "
            f"{currency}={balance}"
        )

    return balance


def build_owned_minimum_reserves(
    conn: sqlite3.Connection,
    *,
    base_currency: str,
    dedicated_bnb_fee_reserve: Decimal,
) -> dict[str, Decimal]:
    """
    Build all physically protected balances that
    exist outside the ETF's ordinary cash/position
    ledger.

    Currently:
      - contribution funding reserve in base currency
      - dedicated BNB fee reserve
    """

    base_currency = base_currency.upper()

    dedicated_bnb_fee_reserve = Decimal(
        dedicated_bnb_fee_reserve
    )

    if dedicated_bnb_fee_reserve < ZERO:
        raise RuntimeError(
            "Dedicated BNB fee reserve "
            "cannot be negative."
        )

    contribution_funding = (
        get_contribution_funding_balance(
            conn,
            base_currency,
        )
    )

    reserves: dict[str, Decimal] = {}

    if contribution_funding > ZERO:
        reserves[base_currency] = (
            contribution_funding
        )

    if dedicated_bnb_fee_reserve > ZERO:
        reserves["BNB"] = (
            reserves.get(
                "BNB",
                ZERO,
            )
            + dedicated_bnb_fee_reserve
        )

    return reserves



def build_owned_minimum_reserves_from_database(
    database,
    *,
    base_currency: str,
    dedicated_bnb_fee_reserve: Decimal,
) -> dict[str, Decimal]:
    """
    Read owned reserves using the project's
    normal Database connection manager.

    This performs no schema creation and no
    funding-ledger mutation.
    """

    with database.connection() as conn:

        return build_owned_minimum_reserves(
            conn,
            base_currency=base_currency,
            dedicated_bnb_fee_reserve=(
                dedicated_bnb_fee_reserve
            ),
        )

