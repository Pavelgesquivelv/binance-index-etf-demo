from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.index.feed_bridge import (
    MISSING_AFTER_GRACE,
    NOT_DUE,
    READY_TO_IMPORT,
    WAITING_FOR_SOURCE,
    last_calendar_day,
    resolve_feed_bridge_expectation,
)


SOURCE = (
    "/home/cryptobot/crypto_index/"
    "runs/daily/portfolios"
)

TEMPLATE = (
    "portfolio_{cutoff_date}.json"
)


# --------------------------------------------------
# Last-calendar-day resolution.
# --------------------------------------------------

assert (
    last_calendar_day(
        2026,
        9,
    ).isoformat()
    == "2026-09-30"
)

assert (
    last_calendar_day(
        2026,
        10,
    ).isoformat()
    == "2026-10-31"
)

assert (
    last_calendar_day(
        2026,
        11,
    ).isoformat()
    == "2026-11-30"
)

assert (
    last_calendar_day(
        2027,
        2,
    ).isoformat()
    == "2027-02-28"
)

assert (
    last_calendar_day(
        2028,
        2,
    ).isoformat()
    == "2028-02-29"
)


# --------------------------------------------------
# Sep 28: September feed is not due yet.
#
# CDMX = UTC-6, therefore:
# 12:00 UTC = 06:00 CDMX.
# --------------------------------------------------

before_month_end = (
    resolve_feed_bridge_expectation(
        now_utc=datetime(
            2026,
            9,
            28,
            12,
            0,
            tzinfo=timezone.utc,
        ),
        timezone_name=(
            "America/Mexico_City"
        ),
        time_local="07:00",
        grace_minutes=15,
        source_directory=SOURCE,
        filename_template=TEMPLATE,
        source_exists=False,
    )
)

assert (
    before_month_end.status
    == NOT_DUE
)

assert (
    before_month_end
    .expected_filename
    == "portfolio_2026-09-30.json"
)


# --------------------------------------------------
# Sep 30 07:00 CDMX:
# source not present -> waiting.
# --------------------------------------------------

waiting = (
    resolve_feed_bridge_expectation(
        now_utc=datetime(
            2026,
            9,
            30,
            13,
            0,
            tzinfo=timezone.utc,
        ),
        timezone_name=(
            "America/Mexico_City"
        ),
        time_local="07:00",
        grace_minutes=15,
        source_directory=SOURCE,
        filename_template=TEMPLATE,
        source_exists=False,
    )
)

assert (
    waiting.status
    == WAITING_FOR_SOURCE
)


# --------------------------------------------------
# Sep 30 07:05 CDMX:
# exact expected source exists -> ready.
# --------------------------------------------------

ready = (
    resolve_feed_bridge_expectation(
        now_utc=datetime(
            2026,
            9,
            30,
            13,
            5,
            tzinfo=timezone.utc,
        ),
        timezone_name=(
            "America/Mexico_City"
        ),
        time_local="07:00",
        grace_minutes=15,
        source_directory=SOURCE,
        filename_template=TEMPLATE,
        source_exists=True,
    )
)

assert (
    ready.status
    == READY_TO_IMPORT
)

assert (
    ready.expected_source_path
    == (
        Path(SOURCE)
        / "portfolio_2026-09-30.json"
    )
)


# --------------------------------------------------
# 07:14:59 CDMX:
# still inside grace window.
# --------------------------------------------------

still_waiting = (
    resolve_feed_bridge_expectation(
        now_utc=datetime(
            2026,
            9,
            30,
            13,
            14,
            59,
            tzinfo=timezone.utc,
        ),
        timezone_name=(
            "America/Mexico_City"
        ),
        time_local="07:00",
        grace_minutes=15,
        source_directory=SOURCE,
        filename_template=TEMPLATE,
        source_exists=False,
    )
)

assert (
    still_waiting.status
    == WAITING_FOR_SOURCE
)


# --------------------------------------------------
# 07:15 CDMX:
# source still absent -> hard missing state.
# --------------------------------------------------

missing = (
    resolve_feed_bridge_expectation(
        now_utc=datetime(
            2026,
            9,
            30,
            13,
            15,
            tzinfo=timezone.utc,
        ),
        timezone_name=(
            "America/Mexico_City"
        ),
        time_local="07:00",
        grace_minutes=15,
        source_directory=SOURCE,
        filename_template=TEMPLATE,
        source_exists=False,
    )
)

assert (
    missing.status
    == MISSING_AFTER_GRACE
)


print(
    "Feed bridge calendar test: OK"
)

print(
    "September 2026 : "
    "portfolio_2026-09-30.json"
)

print(
    "October 2026   : "
    "portfolio_2026-10-31.json"
)

print(
    "November 2026  : "
    "portfolio_2026-11-30.json"
)

print(
    "February 2028  : "
    "portfolio_2028-02-29.json"
)

print(
    "Before cutoff  : NOT_DUE"
)

print(
    "Grace window   : WAITING_FOR_SOURCE"
)

print(
    "Source present : READY_TO_IMPORT"
)

print(
    "After grace    : MISSING_AFTER_GRACE"
)
