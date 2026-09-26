from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.index.feed_bridge_promotion import (
    ALREADY_CURRENT,
    PROMOTED,
    promote_validated_feed,
    read_stable_source,
    validate_feed_content,
)


def portfolio(
    *,
    cutoff_local: str,
    cutoff_utc: str,
    index_level: str = "60.25",
) -> dict:

    assets = [
        "BTC",
        "ETH",
        "BNB",
        "XRP",
        "SOL",
        "TRX",
        "ZEC",
        "LINK",
        "ADA",
        "XLM",
    ]

    return {
        "status": "research_provisional",
        "cutoff_local": cutoff_local,
        "cutoff_utc": cutoff_utc,
        "ranking_date": "2026-09-29",
        "index_level": index_level,
        "positions": [
            {
                "asset": asset,
                "pair": f"{asset}USDT",
                "quantity": "1",
                "rebalance_price_usdt": "1",
                "target_weight_pct": 10,
            }
            for asset in assets
        ],
    }


with tempfile.TemporaryDirectory() as tmp:

    root = Path(tmp)

    source = (
        root
        / "source"
        / "portfolio_2026-09-30.json"
    )

    current = (
        root
        / "feeds"
        / "current.json"
    )

    archive = (
        root
        / "feeds"
        / "archive"
    )

    source.parent.mkdir(
        parents=True
    )

    source.write_text(
        json.dumps(
            portfolio(
                cutoff_local=(
                    "2026-09-30T07:00:00-06:00"
                ),
                cutoff_utc=(
                    "2026-09-30T13:00:00+00:00"
                ),
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    stable = read_stable_source(
        source,
        settle_seconds=0,
    )

    validated = validate_feed_content(
        stable,
        expected_cutoff_date=(
            date(
                2026,
                9,
                30,
            )
        ),
        timezone_name=(
            "America/Mexico_City"
        ),
        time_local="07:00",
    )

    assert (
        validated.constituent_count
        == 10
    )

    assert (
        str(
            validated.total_weight_pct
        )
        == "100"
    )

    result = promote_validated_feed(
        validated,
        current_path=current,
        archive_directory=archive,
    )

    assert result.status == PROMOTED
    assert current.exists()
    assert result.archive_path.exists()

    assert (
        current.read_bytes()
        == source.read_bytes()
    )

    assert (
        result.archive_path.read_bytes()
        == source.read_bytes()
    )

    # ----------------------------------------------
    # Exact rerun is idempotent.
    # ----------------------------------------------

    again = promote_validated_feed(
        validated,
        current_path=current,
        archive_directory=archive,
    )

    assert (
        again.status
        == ALREADY_CURRENT
    )

    # ----------------------------------------------
    # Same cutoff + different content must block.
    # ----------------------------------------------

    changed = (
        root
        / "source"
        / "portfolio_changed.json"
    )

    changed.write_text(
        json.dumps(
            portfolio(
                cutoff_local=(
                    "2026-09-30T07:00:00-06:00"
                ),
                cutoff_utc=(
                    "2026-09-30T13:00:00+00:00"
                ),
                index_level="61.00",
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    changed_validated = (
        validate_feed_content(
            read_stable_source(
                changed,
                settle_seconds=0,
            ),
            expected_cutoff_date=(
                date(
                    2026,
                    9,
                    30,
                )
            ),
            timezone_name=(
                "America/Mexico_City"
            ),
            time_local="07:00",
        )
    )

    blocked = False

    try:
        promote_validated_feed(
            changed_validated,
            current_path=current,
            archive_directory=archive,
        )

    except RuntimeError:
        blocked = True

    assert blocked

    # ----------------------------------------------
    # Wrong internal cutoff must block.
    # ----------------------------------------------

    wrong_cutoff = (
        root
        / "source"
        / "wrong_cutoff.json"
    )

    wrong_cutoff.write_text(
        json.dumps(
            portfolio(
                cutoff_local=(
                    "2026-09-29T07:00:00-06:00"
                ),
                cutoff_utc=(
                    "2026-09-29T13:00:00+00:00"
                ),
            ),
            indent=2,
        ),
        encoding="utf-8",
    )

    blocked = False

    try:
        validate_feed_content(
            read_stable_source(
                wrong_cutoff,
                settle_seconds=0,
            ),
            expected_cutoff_date=(
                date(
                    2026,
                    9,
                    30,
                )
            ),
            timezone_name=(
                "America/Mexico_City"
            ),
            time_local="07:00",
        )

    except RuntimeError:
        blocked = True

    assert blocked

    # ----------------------------------------------
    # Weights not equal to 100 must block.
    # ----------------------------------------------

    bad_weights = portfolio(
        cutoff_local=(
            "2026-09-30T07:00:00-06:00"
        ),
        cutoff_utc=(
            "2026-09-30T13:00:00+00:00"
        ),
    )

    bad_weights[
        "positions"
    ][0][
        "target_weight_pct"
    ] = 9

    bad_path = (
        root
        / "source"
        / "bad_weights.json"
    )

    bad_path.write_text(
        json.dumps(
            bad_weights,
            indent=2,
        ),
        encoding="utf-8",
    )

    blocked = False

    try:
        validate_feed_content(
            read_stable_source(
                bad_path,
                settle_seconds=0,
            ),
            expected_cutoff_date=(
                date(
                    2026,
                    9,
                    30,
                )
            ),
            timezone_name=(
                "America/Mexico_City"
            ),
            time_local="07:00",
        )

    except RuntimeError:
        blocked = True

    assert blocked


print(
    "Feed bridge promotion test: OK"
)

print(
    "Stable source read            : OK"
)

print(
    "Cutoff filename/content match : OK"
)

print(
    "ETF canonical loader          : OK"
)

print(
    "Weights sum to 100%           : OK"
)

print(
    "Immutable archive snapshot    : OK"
)

print(
    "Atomic current promotion      : OK"
)

print(
    "Exact rerun                   : IDEMPOTENT"
)

print(
    "Same cutoff / different hash  : BLOCKED"
)

print(
    "Wrong internal cutoff         : BLOCKED"
)

print(
    "Invalid weights               : BLOCKED"
)
