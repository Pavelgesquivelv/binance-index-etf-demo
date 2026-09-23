from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.execution.execution_metrics import (
    calculate_execution_metrics,
    value_commission_usdc,
)
from src.storage.database import Database


ZERO = Decimal("0")


def load_config() -> dict:
    with (
        ROOT / "config" / "runtime.yaml"
    ).open(
        "r",
        encoding="utf-8",
    ) as file:
        return yaml.safe_load(file)


def decimal_or_zero(
    value,
) -> Decimal:
    if value is None:
        return ZERO

    return Decimal(str(value))


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--run-id",
        type=int,
        required=True,
    )

    args = parser.parse_args()

    config = load_config()

    base_currency = (
        config["fund"]["base_currency"]
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

    # =====================================================
    # Load everything required for this run.
    # =====================================================

    with database.connection() as conn:

        run = conn.execute(
            """
            SELECT *
            FROM rebalance_runs
            WHERE id = ?
            """,
            (args.run_id,),
        ).fetchone()

        if run is None:
            raise RuntimeError(
                f"Run {args.run_id} "
                "not found."
            )

        orders = conn.execute(
            """
            SELECT
                o.*,
                l.local_status
            FROM orders o
            JOIN order_lifecycle l
              ON l.order_id = o.id
            WHERE o.rebalance_run_id = ?
            ORDER BY o.id
            """,
            (args.run_id,),
        ).fetchall()

        fill_rows = conn.execute(
            """
            SELECT
                f.*,
                o.client_order_id
            FROM fills f
            JOIN orders o
              ON o.id = f.order_id
            WHERE o.rebalance_run_id = ?
            ORDER BY
                o.id,
                f.id
            """,
            (args.run_id,),
        ).fetchall()

        benchmark_rows = conn.execute(
            """
            SELECT
                b.*
            FROM execution_benchmarks b
            JOIN orders o
              ON o.id = b.order_id
            WHERE o.rebalance_run_id = ?
            """,
            (args.run_id,),
        ).fetchall()

    # =====================================================
    # Organize fills / benchmarks.
    # =====================================================

    fills_by_order = defaultdict(list)

    for fill in fill_rows:
        fills_by_order[
            fill["order_id"]
        ].append(fill)

    benchmarks = {
        row["order_id"]: row
        for row in benchmark_rows
    }

    # Raw commission totals by asset.
    # Keep Decimal precision.
    raw_fees = defaultdict(
        lambda: ZERO
    )

    for fill in fill_rows:
        raw_fees[
            fill[
                "commission_asset"
            ].upper()
        ] += Decimal(
            fill["commission"]
        )

    # =====================================================
    # Header
    # =====================================================

    print("=" * 118)

    print(
        f"ETF REBALANCE AUDIT - "
        f"RUN {args.run_id}"
    )

    print("=" * 118)

    print()

    print(
        f"Status              : "
        f"{run['status']}"
    )

    print(
        f"Started UTC         : "
        f"{run['started_at_utc']}"
    )

    print(
        f"Completed UTC       : "
        f"{run['completed_at_utc']}"
    )

    print(
        f"Feed cutoff         : "
        f"{run['cutoff_utc']}"
    )

    print(
        f"Index level         : "
        f"{run['index_level']}"
    )

    print(
        f"NAV before          : "
        f"{run['nav_before_usdc']} "
        f"{base_currency}"
    )

    # =====================================================
    # Orders
    # =====================================================

    print()
    print("ORDERS")
    print("-" * 118)

    total_quote = ZERO

    for order in orders:

        quote = decimal_or_zero(
            order[
                "cumulative_quote_quantity"
            ]
        )

        total_quote += quote

        fill_count = len(
            fills_by_order[
                order["id"]
            ]
        )

        print(
            f"{order['client_order_id']:28} "
            f"{order['side']:4} "
            f"{order['symbol']:12} "
            f"status="
            f"{order['exchange_status']:10} "
            f"local="
            f"{order['local_status']:10} "
            f"qty="
            f"{order['executed_quantity']} "
            f"quote="
            f"{quote} "
            f"fills="
            f"{fill_count}"
        )

    print("-" * 118)

    print()

    print(
        f"Orders accounted    : "
        f"{len(orders)}"
    )

    print(
        f"Total quote         : "
        f"{total_quote} "
        f"{base_currency}"
    )

    # =====================================================
    # Raw fees
    # =====================================================

    print()
    print("RAW FEES")
    print("-" * 118)

    if not raw_fees:
        print(
            "No execution fees recorded."
        )

    else:
        for asset in sorted(
            raw_fees
        ):
            print(
                f"{asset:8} "
                f"{raw_fees[asset]}"
            )

    print("-" * 118)

    # =====================================================
    # Execution quality
    # =====================================================

    print()
    print("EXECUTION QUALITY")
    print("-" * 118)

    benchmark_count = 0
    missing_benchmark_count = 0

    total_benchmark_notional = ZERO

    total_spread_cost = ZERO
    total_slippage_cost = ZERO
    total_execution_cost = ZERO
    total_fee_cost = ZERO
    total_shortfall = ZERO

    metrics_order_count = 0
    full_shortfall_count = 0

    unvalued_fee_orders = []

    for order in orders:

        order_id = order["id"]

        benchmark = benchmarks.get(
            order_id
        )

        if benchmark is None:

            missing_benchmark_count += 1

            print(
                f"{order['asset']:6} "
                f"{order['side']:4} "
                f"benchmark=N/A "
                f"(not captured)"
            )

            continue

        benchmark_count += 1

        quantity = decimal_or_zero(
            order["executed_quantity"]
        )

        quote_quantity = (
            decimal_or_zero(
                order[
                    "cumulative_quote_quantity"
                ]
            )
        )

        if (
            quantity <= ZERO
            or quote_quantity <= ZERO
        ):

            print(
                f"{order['asset']:6} "
                f"{order['side']:4} "
                "metrics=N/A "
                "(zero execution)"
            )

            continue

        bid = Decimal(
            benchmark["bid_price"]
        )

        ask = Decimal(
            benchmark["ask_price"]
        )

        mid = Decimal(
            benchmark["mid_price"]
        )

        bnb_mid_usdc = None

        if (
            benchmark[
                "bnb_mid_usdc"
            ]
            is not None
        ):
            bnb_mid_usdc = Decimal(
                benchmark[
                    "bnb_mid_usdc"
                ]
            )

        # ---------------------------------------------
        # Value actual fees using prices captured
        # at the benchmark timestamp.
        # ---------------------------------------------

        fee_cost = ZERO
        fee_complete = True

        for fill in fills_by_order[
            order_id
        ]:

            commission = Decimal(
                fill["commission"]
            )

            if commission == ZERO:
                continue

            valued_fee = (
                value_commission_usdc(
                    commission=commission,
                    commission_asset=(
                        fill[
                            "commission_asset"
                        ]
                    ),
                    base_asset=(
                        order["asset"]
                    ),
                    quote_asset=(
                        base_currency
                    ),
                    benchmark_mid=mid,
                    bnb_mid_usdc=(
                        bnb_mid_usdc
                    ),
                )
            )

            if valued_fee is None:

                fee_complete = False
                continue

            fee_cost += valued_fee

        # We can always calculate execution
        # quality even if some unusual fee asset
        # cannot be valued.
        metrics = (
            calculate_execution_metrics(
                side=order["side"],
                quantity=quantity,
                quote_quantity=(
                    quote_quantity
                ),
                bid=bid,
                ask=ask,
                mid=mid,
                fee_cost_usdc=(
                    fee_cost
                    if fee_complete
                    else ZERO
                ),
            )
        )

        metrics_order_count += 1

        total_benchmark_notional += (
            metrics.benchmark_notional
        )

        total_spread_cost += (
            metrics.spread_cost_usdc
        )

        total_slippage_cost += (
            metrics.slippage_cost_usdc
        )

        total_execution_cost += (
            metrics
            .execution_cost_vs_mid_usdc
        )

        if fee_complete:

            total_fee_cost += (
                metrics.fee_cost_usdc
            )

            total_shortfall += (
                metrics
                .implementation_shortfall_usdc
            )

            full_shortfall_count += 1

        else:

            unvalued_fee_orders.append(
                order[
                    "client_order_id"
                ]
            )

        fee_text = (
            f"{fee_cost:.8f}"
            if fee_complete
            else "N/A"
        )

        shortfall_text = (
            f"{metrics.implementation_shortfall_usdc:+.8f}"
            if fee_complete
            else "N/A"
        )

        shortfall_bps_text = (
            f"{metrics.implementation_shortfall_bps:+.4f}"
            if fee_complete
            else "N/A"
        )

        print(
            f"{order['asset']:6} "
            f"{order['side']:4} "
            f"avg={metrics.average_fill_price:.8f} "
            f"mid={mid:.8f} "
            f"spread={metrics.spread_cost_usdc:+.8f} "
            f"slip={metrics.slippage_cost_usdc:+.8f} "
            f"exec={metrics.execution_cost_vs_mid_usdc:+.8f} "
            f"fee={fee_text} "
            f"IS={shortfall_text} "
            f"bps={shortfall_bps_text}"
        )

    print("-" * 118)

    print()

    print(
        f"Benchmark coverage  : "
        f"{benchmark_count}/"
        f"{len(orders)} orders"
    )

    # =====================================================
    # Totals only when benchmarks exist.
    # =====================================================

    if metrics_order_count > 0:

        print()
        print("EXECUTION TOTALS")
        print("-" * 118)

        print(
            f"Benchmark notional  : "
            f"{total_benchmark_notional:.8f} "
            f"{base_currency}"
        )

        print(
            f"Spread crossing     : "
            f"{total_spread_cost:+.8f} "
            f"{base_currency}"
        )

        print(
            f"Slippage vs touch   : "
            f"{total_slippage_cost:+.8f} "
            f"{base_currency}"
        )

        print(
            f"Execution vs mid    : "
            f"{total_execution_cost:+.8f} "
            f"{base_currency}"
        )

        if (
            full_shortfall_count
            == metrics_order_count
        ):

            print(
                f"Fees valued         : "
                f"{total_fee_cost:.8f} "
                f"{base_currency}"
            )

            print(
                f"Implementation "
                f"shortfall : "
                f"{total_shortfall:+.8f} "
                f"{base_currency}"
            )

            if (
                total_benchmark_notional
                > ZERO
            ):

                total_shortfall_bps = (
                    total_shortfall
                    / total_benchmark_notional
                    * Decimal("10000")
                )

                print(
                    f"Shortfall           : "
                    f"{total_shortfall_bps:+.4f} "
                    f"bps"
                )

        else:

            print(
                "Fees valued         : "
                "INCOMPLETE"
            )

            print(
                "Implementation "
                "shortfall : N/A"
            )

        print("-" * 118)

    # =====================================================
    # Warnings / historical coverage
    # =====================================================

    if (
        len(orders) > 0
        and benchmark_count == 0
    ):

        print()

        print(
            "NOTE: This rebalance predates "
            "execution benchmark capture."
        )

        print(
            "Spread, slippage and "
            "implementation shortfall cannot "
            "be reconstructed reliably."
        )

    elif missing_benchmark_count > 0:

        print()

        print(
            "WARNING: Some orders do not "
            "have execution benchmarks."
        )

    if unvalued_fee_orders:

        print()

        print(
            "WARNING: Some commission assets "
            "could not be valued."
        )

        for client_order_id in (
            unvalued_fee_orders
        ):
            print(
                f"  {client_order_id}"
            )

    # =====================================================
    # Lifecycle integrity
    # =====================================================

    unresolved = [
        order
        for order in orders
        if (
            order["local_status"]
            != "ACCOUNTED"
        )
    ]

    print()
    print("LIFECYCLE")
    print("-" * 118)

    print(
        f"Non-accounted orders: "
        f"{len(unresolved)}"
    )

    print()

    if unresolved:

        print(
            "AUDIT RESULT         : "
            "REVIEW REQUIRED"
        )

    else:

        print(
            "AUDIT RESULT         : OK"
        )


if __name__ == "__main__":
    main()
