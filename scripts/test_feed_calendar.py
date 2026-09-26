from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.index.feed_calendar import (
    CURRENT,
    FUTURE_INVALID,
    STALE_MISSING_MONTHLY_REBALANCE,
    WAITING_FOR_MONTH_END_FEED,
    classify_feed_cutoff,
)


AUGUST = (
    "2026-08-31T13:00:00+00:00"
)

SEPTEMBER = (
    "2026-09-30T13:00:00+00:00"
)

JULY = (
    "2026-07-31T13:00:00+00:00"
)


def utc(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int = 0,
    second: int = 0,
) -> datetime:

    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=timezone.utc,
    )


# Sep 25:
# Aug-31 is still the active portfolio.
state = classify_feed_cutoff(
    AUGUST,
    now_utc=utc(
        2026,
        9,
        25,
        23,
    ),
)

assert state.status == CURRENT


# Sep 30 06:59 CDMX:
# old portfolio remains current.
state = classify_feed_cutoff(
    AUGUST,
    now_utc=utc(
        2026,
        9,
        30,
        12,
        59,
    ),
)

assert state.status == CURRENT


# Sep 30 07:00 CDMX:
# transition window begins.
state = classify_feed_cutoff(
    AUGUST,
    now_utc=utc(
        2026,
        9,
        30,
        13,
        0,
    ),
)

assert (
    state.status
    == WAITING_FOR_MONTH_END_FEED
)


# Still inside 07:00-07:14 window.
state = classify_feed_cutoff(
    AUGUST,
    now_utc=utc(
        2026,
        9,
        30,
        13,
        14,
        59,
    ),
)

assert (
    state.status
    == WAITING_FOR_MONTH_END_FEED
)


# At 07:15 CDMX, Sep-30 is mandatory.
state = classify_feed_cutoff(
    AUGUST,
    now_utc=utc(
        2026,
        9,
        30,
        13,
        15,
    ),
)

assert (
    state.status
    == STALE_MISSING_MONTHLY_REBALANCE
)


# New Sep-30 portfolio during the
# transition window is immediately current.
state = classify_feed_cutoff(
    SEPTEMBER,
    now_utc=utc(
        2026,
        9,
        30,
        13,
        5,
    ),
)

assert state.status == CURRENT


# A portfolio older than the active
# monthly cutoff is stale.
state = classify_feed_cutoff(
    JULY,
    now_utc=utc(
        2026,
        9,
        25,
        23,
    ),
)

assert (
    state.status
    == STALE_MISSING_MONTHLY_REBALANCE
)


# Sep-30 cannot exist as a valid feed
# on Sep-25.
state = classify_feed_cutoff(
    SEPTEMBER,
    now_utc=utc(
        2026,
        9,
        25,
        23,
    ),
)

assert state.status == FUTURE_INVALID


# Oct-01 requires Sep-30.
state = classify_feed_cutoff(
    AUGUST,
    now_utc=utc(
        2026,
        10,
        1,
        12,
    ),
)

assert (
    state.status
    == STALE_MISSING_MONTHLY_REBALANCE
)


state = classify_feed_cutoff(
    SEPTEMBER,
    now_utc=utc(
        2026,
        10,
        1,
        12,
    ),
)

assert state.status == CURRENT


print(
    "Feed calendar test: OK"
)

print(
    "Sep-25 Aug-31 feed : CURRENT"
)

print(
    "Sep-30 <07:00      : CURRENT"
)

print(
    "Sep-30 07:00-07:14 : "
    "WAITING_FOR_MONTH_END_FEED"
)

print(
    "Sep-30 >=07:15     : "
    "STALE if Sep feed missing"
)

print(
    "Oct-01 Sep-30 feed : CURRENT"
)
