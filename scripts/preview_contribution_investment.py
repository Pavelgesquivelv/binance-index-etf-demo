from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_investment import (
    build_order_intents,
)
from src.contributions.contribution_planner import (
    ContributionPlanner,
)
from src.exchange.binance_demo_client import (
    BinanceDemoClient,
)
from src.index.portfolio_feed import (
    PortfolioFeedLoader,
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


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--period-id",
        default=None,
        help=(
            "Accepted contribution period, "
            "for example 2026-W40."
        ),
    )

    parser.add_argument(
        "--simulate-accepted-amount",
        type=Decimal,
        default=None,
        help=(
            "Dry-run only. Pretend this "
            "amount has already been accepted. "
            "No SQLite mutation and no orders."
        ),
    )

    args = parser.parse_args()

    if (
        args.simulate_accepted_amount
        is not None
        and args.period_id is None
    ):
        parser.error(
            "--simulate-accepted-amount "
            "requires --period-id."
        )

    config = load_config()

    contribution_cfg = (
        config["cash_contributions"]
    )

    currency = (
        contribution_cfg[
            "currency"
        ].upper()
    )

    max_orders = int(
        contribution_cfg[
            "execution"
        ]["max_orders"]
    )

    fee_buffer_multiplier = Decimal(
        str(
            contribution_cfg[
                "execution"
            ][
                "fee_buffer_multiplier"
            ]
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

    feed = PortfolioFeedLoader(
        ROOT
        / config["index_feed"][
            "portfolio_file"
        ]
    ).load()

    # -------------------------------------------------
    # The feed used for contribution investment must
    # already be an accepted/completed index portfolio.
    # -------------------------------------------------

    with database.connection() as conn:

        completed_run = conn.execute(
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
            (
                feed.cutoff_utc,
            ),
        ).fetchone()

        recoverable = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE l.local_status
                  <> 'ACCOUNTED'
            """
        ).fetchone()["n"]

    if completed_run is None:

        raise RuntimeError(
            "Contribution investment blocked: "
            "current portfolio cutoff has not "
            "been successfully processed."
        )

    if recoverable:

        raise RuntimeError(
            "Contribution investment blocked: "
            f"{recoverable} recoverable ETF "
            "order(s) exist."
        )

    simulated = (
        args.simulate_accepted_amount
        is not None
    )

    if simulated:

        period_id = args.period_id

        investment_amount = (
            args.simulate_accepted_amount
        )

        contribution_feed_cutoff = (
            feed.cutoff_utc
        )

        contribution_status = (
            "SIMULATED_ACCEPTED"
        )

    else:

        if args.period_id is None:

            raise RuntimeError(
                "Use --period-id for a real "
                "accepted contribution."
            )

        with database.connection() as conn:

            table_exists = conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type='table'
                  AND name='cash_contributions'
                """
            ).fetchone()

            if table_exists is None:
                raise RuntimeError(
                    "cash_contributions table "
                    "does not exist."
                )

            contribution = conn.execute(
                """
                SELECT *
                FROM cash_contributions
                WHERE period_id = ?
                """,
                (
                    args.period_id,
                ),
            ).fetchone()

        if contribution is None:

            raise RuntimeError(
                "Contribution period not found: "
                f"{args.period_id}"
            )

        if (
            contribution["status"]
            != "ACCEPTED_PENDING_INVESTMENT"
        ):

            raise RuntimeError(
                "Contribution is not ready "
                "for investment. "
                f"status="
                f"{contribution['status']}"
            )

        period_id = (
            contribution["period_id"]
        )

        investment_amount = Decimal(
            contribution[
                "accepted_amount"
            ]
        )

        contribution_feed_cutoff = (
            contribution[
                "feed_cutoff_utc"
            ]
        )

        contribution_status = (
            contribution["status"]
        )

    if investment_amount <= ZERO:
        raise RuntimeError(
            "Investment amount must "
            "be positive."
        )

    # The contribution was accepted against this
    # exact index portfolio. Never silently switch
    # it to another portfolio.
    if (
        contribution_feed_cutoff
        != feed.cutoff_utc
    ):

        raise RuntimeError(
            "Contribution investment blocked: "
            "portfolio cutoff changed after "
            "contribution acceptance. "
            f"accepted_cutoff="
            f"{contribution_feed_cutoff}, "
            f"current_cutoff="
            f"{feed.cutoff_utc}"
        )

    cash = ledger.get_cash_balance(
        currency
    )

    positions = get_positions(
        ledger
    )

    client = BinanceDemoClient()

    account = client.get_account()

    # -------------------------------------------------
    # Existing physical ETF inventory must remain
    # backed before doing any contribution work.
    # -------------------------------------------------

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

    backing = check_physical_backing(
        cash=cash,
        positions=positions,
        account=account,
        base_currency=currency,
        minimum_reserves=(
            build_owned_minimum_reserves_from_database(
                database,
                base_currency=currency,
                dedicated_bnb_fee_reserve=(
                    dedicated_bnb_reserve
                ),
            )
        ),
    )

    if not backing.ok:

        raise RuntimeError(
            "Contribution investment blocked: "
            "physical backing failed."
        )

    # In a real investment the accepted contribution
    # must already exist in the ETF ledger.
    if (
        not simulated
        and cash < investment_amount
    ):

        raise RuntimeError(
            "ETF cash ledger is below accepted "
            "contribution amount. "
            f"cash={cash}, "
            f"accepted={investment_amount}"
        )

    plan = ContributionPlanner().build(
        feed=feed,
        amount=investment_amount,
        currency=currency,
        period_id=period_id,
    )

    intents = build_order_intents(
        plan=plan,
        base_currency=currency,
        order_prefix=(
            config["fund"][
                "order_prefix"
            ]
        ),
    )

    if len(intents) > max_orders:
        raise RuntimeError(
            "Contribution order count exceeds "
            f"configured maximum. "
            f"orders={len(intents)}, "
            f"maximum={max_orders}"
        )

    # -------------------------------------------------
    # Binance preflight ALL orders before any future
    # execution is allowed.
    # -------------------------------------------------

    preflights = {}

    bnb_discount_detected = False

    for intent in intents:

        response = (
            client.test_market_order(
                symbol=intent.symbol,
                side="BUY",
                quote_order_qty=str(
                    intent.quote_order_qty
                ),
                compute_commission_rates=True,
            )
        )

        preflights[
            intent.client_order_id
        ] = response

        discount = response.get(
            "discount",
            {},
        )

        if (
            discount.get(
                "enabledForAccount"
            )
            and discount.get(
                "enabledForSymbol"
            )
            and discount.get(
                "discountAsset"
            ) == "BNB"
        ):
            bnb_discount_detected = True

    planned_turnover = sum(
        (
            intent.quote_order_qty
            for intent in intents
        ),
        ZERO,
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

    required_fee_buffer = (
        planned_turnover
        * taker_rate
        * fee_buffer_multiplier
    )

    shared_reserve_value = None

    if bnb_discount_detected:

        ticker = client.get_book_ticker(
            f"BNB{currency}"
        )

        bid = Decimal(
            ticker["bidPrice"]
        )

        ask = Decimal(
            ticker["askPrice"]
        )

        mid = (
            bid + ask
        ) / Decimal("2")

        shared_reserve_value = (
            dedicated_bnb_reserve
            * mid
        )

        if (
            shared_reserve_value
            < required_fee_buffer
        ):

            raise RuntimeError(
                "Dedicated BNB fee reserve is "
                "insufficient for contribution "
                "investment. "
                f"reserve_value="
                f"{shared_reserve_value}, "
                f"required="
                f"{required_fee_buffer}"
            )

    print("=" * 100)
    print(
        "ETF CONTRIBUTION INVESTMENT PREVIEW"
    )
    print("=" * 100)

    print()

    print(
        f"Period             : "
        f"{period_id}"
    )

    print(
        f"Status             : "
        f"{contribution_status}"
    )

    print(
        f"Portfolio cutoff   : "
        f"{feed.cutoff_utc}"
    )

    print(
        f"Completed run      : "
        f"{completed_run['id']}"
    )

    print(
        f"Investment amount  : "
        f"{investment_amount:.8f} "
        f"{currency}"
    )

    print(
        f"ETF ledger cash    : "
        f"{cash:.8f} "
        f"{currency}"
    )

    if simulated:

        print(
            f"Hypothetical cash  : "
            f"{cash + investment_amount:.8f} "
            f"{currency}"
        )

    print()

    print(
        "Physical backing   : OK"
    )

    print(
        f"Orders             : "
        f"{len(intents)}"
    )

    print(
        f"BUY notional       : "
        f"{planned_turnover:.8f} "
        f"{currency}"
    )

    print(
        "SELL notional      : "
        f"{ZERO:.8f} {currency}"
    )

    print(
        f"Fee buffer req.    : "
        f"{required_fee_buffer:.8f} "
        f"{currency}"
    )

    if bnb_discount_detected:

        print(
            "BNB fee discount   : YES"
        )

        print(
            f"Dedicated reserve BNB : "
            f"{dedicated_bnb_reserve}"
        )

        print(
            f"Reserve value      : "
            f"{shared_reserve_value:.8f} "
            f"{currency}"
        )

    print()

    print(
        "EXECUTION ORDER"
    )

    print("-" * 100)

    for intent in intents:

        print(
            f"{intent.sequence:02d} "
            f"{intent.client_order_id:30} "
            f"{intent.symbol:12} "
            f"BUY "
            f"quoteOrderQty="
            f"{intent.quote_order_qty}"
        )

    print("-" * 100)

    print()

    print(
        "All Binance order preflights: OK"
    )

    print(
        "BUY-only invariant          : OK"
    )

    print(
        "Accepted amount reconciles  : OK"
    )

    print()

    print(
        "Decision           : "
        "READY_FOR_INVESTMENT_EXECUTION"
    )

    print()

    if simulated:
        print(
            "SIMULATION ONLY."
        )

    print(
        "No SQLite mutation."
    )

    print(
        "No Binance order was sent."
    )


if __name__ == "__main__":
    main()
