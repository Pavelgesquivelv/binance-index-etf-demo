from __future__ import annotations

import argparse
import os
from decimal import Decimal
from pathlib import Path
import sys

from dotenv import load_dotenv
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")


from src.contributions.funding_initialization import (
    build_funding_initialization_plan,
)
from src.contributions.funding_repository import (
    ContributionFundingRepository,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.portfolio.ledger import (
    PortfolioLedger,
)
from src.portfolio.owned_reserves import (
    build_owned_minimum_reserves_from_database,
)
from src.portfolio.physical_backing import (
    check_physical_backing,
)
from src.storage.database import (
    Database,
)


ZERO = Decimal("0")
INITIAL_FUNDING = Decimal("2000")


def enabled(name: str) -> bool:

    return (
        os.getenv(
            name,
            "false",
        ).strip().lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }
    )


def load_config() -> dict:

    with (
        ROOT
        / "config"
        / "runtime.yaml"
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
        if Decimal(
            row["quantity"]
        ) != ZERO
    }


def snapshot_connection_state(
    conn,
    *,
    currency: str,
) -> dict:

    cash = sum(
        (
            Decimal(row["amount"])
            for row in conn.execute(
                """
                SELECT amount
                FROM cash_ledger
                WHERE asset = ?
                ORDER BY id
                """,
                (currency,),
            ).fetchall()
        ),
        ZERO,
    )

    shares_row = conn.execute(
        """
        SELECT value
        FROM meta
        WHERE key = 'shares_outstanding'
        """
    ).fetchone()

    shares = (
        shares_row["value"]
        if shares_row is not None
        else None
    )

    positions = tuple(
        (
            row["asset"],
            row["quantity"],
            row["average_cost_usdc"],
        )
        for row in conn.execute(
            """
            SELECT
                asset,
                quantity,
                average_cost_usdc
            FROM positions
            ORDER BY asset
            """
        ).fetchall()
    )

    counts = {}

    for table in (
        "cash_contributions",
        "nav_snapshots",
        "orders",
        "fills",
    ):

        counts[table] = (
            conn.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM {table}
                """
            ).fetchone()["n"]
        )

    return {
        "cash": cash,
        "shares": shares,
        "positions": positions,
        "counts": counts,
    }


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--initialize-funding",
        action="store_true",
        help=(
            "Persist the one-time "
            "2000 USDC contribution "
            "funding reserve."
        ),
    )

    args = parser.parse_args()

    config = load_config()

    base_currency = (
        config["fund"][
            "base_currency"
        ].upper()
    )

    if base_currency != "USDC":
        raise RuntimeError(
            "Expected ETF base currency "
            f"USDC; found {base_currency}."
        )

    contribution_currency = (
        config[
            "cash_contributions"
        ][
            "currency"
        ].upper()
    )

    if (
        contribution_currency
        != base_currency
    ):
        raise RuntimeError(
            "Contribution currency does "
            "not match ETF base currency."
        )

    safety_flags = {
        "BINANCE_TRADING_ENABLED":
            enabled(
                "BINANCE_TRADING_ENABLED"
            ),
        "ETF_WEEKLY_AUTOMATION_ENABLED":
            enabled(
                "ETF_WEEKLY_AUTOMATION_ENABLED"
            ),
        "ETF_CONTRIBUTION_EXECUTION_ENABLED":
            enabled(
                "ETF_CONTRIBUTION_EXECUTION_ENABLED"
            ),
    }

    if any(
        safety_flags.values()
    ):
        raise RuntimeError(
            "Funding initialization requires "
            "all trading and automation "
            "flags to remain false."
        )

    dedicated_bnb_reserve = Decimal(
        str(
            config.get(
                "account_isolation",
                {},
            ).get(
                "dedicated_bnb_fee_reserve",
                "0",
            )
        )
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

    repository = (
        ContributionFundingRepository()
    )

    with database.connection() as conn:

        entries = repository.get_entries(
            conn,
            base_currency,
        )

        current_funding = (
            repository.get_balance(
                conn,
                base_currency,
            )
        )

    if entries:
        raise RuntimeError(
            "Contribution funding ledger "
            "already contains entries. "
            "Initialization is one-time only."
        )

    if current_funding != ZERO:
        raise RuntimeError(
            "Contribution funding balance "
            "must be zero before "
            "initialization."
        )

    cash = ledger.get_cash_balance(
        base_currency
    )

    positions = get_positions(
        ledger
    )

    reserves = (
        build_owned_minimum_reserves_from_database(
            database,
            base_currency=base_currency,
            dedicated_bnb_fee_reserve=(
                dedicated_bnb_reserve
            ),
        )
    )

    client = BinanceDemoClient()

    account = client.get_account()

    plan = (
        build_funding_initialization_plan(
            cash=cash,
            positions=positions,
            account=account,
            base_currency=base_currency,
            current_reserves=reserves,
            amount=INITIAL_FUNDING,
        )
    )

    usdc_line = next(
        line
        for line in (
            plan.proposed_backing.lines
        )
        if line.asset
        == base_currency
    )

    with database.connection() as conn:

        before_state = (
            snapshot_connection_state(
                conn,
                currency=base_currency,
            )
        )

    print("=" * 82)
    print(
        "CONTRIBUTION FUNDING INITIALIZATION"
    )
    print("=" * 82)
    print()

    print(
        f"Currency              : "
        f"{base_currency}"
    )

    print(
        f"Current funding       : "
        f"{current_funding:.8f} "
        f"{base_currency}"
    )

    print(
        f"Proposed funding      : "
        f"{INITIAL_FUNDING:.8f} "
        f"{base_currency}"
    )

    print(
        f"ETF ledger cash       : "
        f"{cash:.8f} "
        f"{base_currency}"
    )

    print(
        f"Owned USDC required   : "
        f"{usdc_line.required_total:.8f} "
        f"{base_currency}"
    )

    print(
        f"Binance free USDC     : "
        f"{usdc_line.exchange_free:.8f} "
        f"{base_currency}"
    )

    print(
        f"Unallocated headroom  : "
        f"{usdc_line.surplus:.8f} "
        f"{base_currency}"
    )

    print(
        f"Dedicated BNB reserve : "
        f"{dedicated_bnb_reserve:.8f} BNB"
    )

    print()
    print(
        "Current backing       : OK"
    )

    print(
        "Proposed backing      : OK"
    )

    print(
        "Safety flags          : ALL FALSE"
    )

    print(
        "Binance orders        : NONE"
    )

    if not args.initialize_funding:

        print()
        print(
            "Decision              : DRY_RUN"
        )

        print(
            "No SQLite mutation."
        )

        return

    proposed_reserves = dict(
        reserves
    )

    proposed_reserves[
        base_currency
    ] = (
        proposed_reserves.get(
            base_currency,
            ZERO,
        )
        + INITIAL_FUNDING
    )

    # --------------------------------------------------
    # Atomic initialization.
    #
    # The funding row is not committed until:
    #   - balance is exactly 2000
    #   - fresh physical backing still passes
    #   - no ETF accounting state changed
    #
    # Any exception inside this context rolls back
    # the funding initialization.
    # --------------------------------------------------

    with database.connection() as conn:

        repository.initialize_funding(
            conn,
            currency=base_currency,
            amount=INITIAL_FUNDING,
            notes=(
                "One-time pre-funded "
                "weekly contribution reserve."
            ),
        )

        final_funding = (
            repository.get_balance(
                conn,
                base_currency,
            )
        )

        if (
            final_funding
            != INITIAL_FUNDING
        ):
            raise RuntimeError(
                "Post-initialization funding "
                "balance mismatch. "
                f"expected={INITIAL_FUNDING}, "
                f"actual={final_funding}"
            )

        # Fetch Binance again while the SQLite
        # transaction is still uncommitted.
        final_account = (
            client.get_account()
        )

        final_backing = (
            check_physical_backing(
                cash=cash,
                positions=positions,
                account=final_account,
                base_currency=base_currency,
                minimum_reserves=(
                    proposed_reserves
                ),
            )
        )

        if not final_backing.ok:

            deficits = "; ".join(
                (
                    f"{line.asset}: "
                    f"required="
                    f"{line.required_total}, "
                    f"free="
                    f"{line.exchange_free}, "
                    f"deficit="
                    f"{-line.surplus}"
                )
                for line
                in final_backing.deficits
            )

            raise RuntimeError(
                "Post-initialization physical "
                "backing failed. "
                f"{deficits}"
            )

        after_state = (
            snapshot_connection_state(
                conn,
                currency=base_currency,
            )
        )

        if after_state != before_state:
            raise RuntimeError(
                "Funding initialization changed "
                "ETF accounting state outside "
                "the funding ledger."
            )

    print()
    print(
        "Decision              : INITIALIZED"
    )

    print(
        f"Funding balance       : "
        f"{final_funding:.8f} "
        f"{base_currency}"
    )

    print(
        "ETF cash unchanged    : OK"
    )

    print(
        "ETF positions unchanged: OK"
    )

    print(
        "Shares unchanged      : OK"
    )

    print(
        "NAV history unchanged : OK"
    )

    print(
        "Contribution rows unchanged: OK"
    )

    print(
        "Post-write backing    : OK"
    )

    print(
        "Binance orders        : NONE"
    )


if __name__ == "__main__":
    main()
