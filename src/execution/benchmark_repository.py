from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sqlite3


TEN_THOUSAND = Decimal("10000")


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


class ExecutionBenchmarkRepository:

    def record(
        self,
        conn: sqlite3.Connection,
        *,
        order_id: int,
        bid: Decimal,
        ask: Decimal,
        bnb_mid_usdc: Decimal | None,
    ) -> None:

        if bid <= 0:
            raise ValueError(
                "Benchmark bid must be positive."
            )

        if ask <= 0:
            raise ValueError(
                "Benchmark ask must be positive."
            )

        if ask < bid:
            raise ValueError(
                "Benchmark ask cannot be below bid."
            )

        mid = (
            bid + ask
        ) / Decimal("2")

        spread_abs = (
            ask - bid
        )

        spread_bps = (
            spread_abs
            / mid
            * TEN_THOUSAND
        )

        conn.execute(
            """
            INSERT INTO execution_benchmarks (
                order_id,
                captured_at_utc,
                bid_price,
                ask_price,
                mid_price,
                spread_abs,
                spread_bps,
                bnb_mid_usdc
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                _utc_now(),
                str(bid),
                str(ask),
                str(mid),
                str(spread_abs),
                str(spread_bps),
                (
                    str(bnb_mid_usdc)
                    if bnb_mid_usdc
                    is not None
                    else None
                ),
            ),
        )
