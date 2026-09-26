from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


CURRENT = "CURRENT"
WAITING_FOR_MONTH_END_FEED = (
    "WAITING_FOR_MONTH_END_FEED"
)
STALE_MISSING_MONTHLY_REBALANCE = (
    "STALE_MISSING_MONTHLY_REBALANCE"
)
FUTURE_INVALID = "FUTURE_INVALID"


INDEX_TIMEZONE = "America/Mexico_City"
REBALANCE_HOUR = 7
REBALANCE_MINUTE = 0
GRACE_MINUTES = 15


@dataclass(frozen=True)
class FeedCalendarState:
    status: str
    feed_cutoff_utc: datetime
    feed_cutoff_local: datetime
    expected_cutoff_local: datetime
    previous_cutoff_local: datetime
    grace_deadline_local: datetime


def _month_end_cutoff(
    year: int,
    month: int,
    zone: ZoneInfo,
) -> datetime:

    last_day = monthrange(
        year,
        month,
    )[1]

    return datetime(
        year,
        month,
        last_day,
        REBALANCE_HOUR,
        REBALANCE_MINUTE,
        tzinfo=zone,
    )


def _previous_month(
    year: int,
    month: int,
) -> tuple[int, int]:

    if month == 1:
        return year - 1, 12

    return year, month - 1


def classify_feed_cutoff(
    cutoff_utc: str,
    *,
    now_utc: datetime | None = None,
) -> FeedCalendarState:

    zone = ZoneInfo(
        INDEX_TIMEZONE
    )

    feed_cutoff = datetime.fromisoformat(
        cutoff_utc
    )

    if feed_cutoff.tzinfo is None:
        raise ValueError(
            "Portfolio cutoff_utc must "
            "contain timezone information."
        )

    feed_cutoff_utc = (
        feed_cutoff.astimezone(
            timezone.utc
        )
    )

    feed_cutoff_local = (
        feed_cutoff.astimezone(
            zone
        )
    )

    if now_utc is None:
        now_utc = datetime.now(
            timezone.utc
        )

    if now_utc.tzinfo is None:
        raise ValueError(
            "now_utc must contain "
            "timezone information."
        )

    now_utc = now_utc.astimezone(
        timezone.utc
    )

    now_local = now_utc.astimezone(
        zone
    )

    current_month_cutoff = (
        _month_end_cutoff(
            now_local.year,
            now_local.month,
            zone,
        )
    )

    previous_year, previous_month = (
        _previous_month(
            now_local.year,
            now_local.month,
        )
    )

    previous_cutoff = (
        _month_end_cutoff(
            previous_year,
            previous_month,
            zone,
        )
    )

    grace_deadline = (
        current_month_cutoff
        + timedelta(
            minutes=GRACE_MINUTES
        )
    )

    if (
        feed_cutoff_utc
        > now_utc
    ):
        status = FUTURE_INVALID

    elif (
        now_local
        < current_month_cutoff
    ):
        if (
            feed_cutoff_local
            == previous_cutoff
        ):
            status = CURRENT

        elif (
            feed_cutoff_local
            < previous_cutoff
        ):
            status = (
                STALE_MISSING_MONTHLY_REBALANCE
            )

        else:
            status = FUTURE_INVALID

    elif (
        now_local
        < grace_deadline
    ):
        if (
            feed_cutoff_local
            == current_month_cutoff
        ):
            status = CURRENT

        elif (
            feed_cutoff_local
            == previous_cutoff
        ):
            status = (
                WAITING_FOR_MONTH_END_FEED
            )

        elif (
            feed_cutoff_local
            < previous_cutoff
        ):
            status = (
                STALE_MISSING_MONTHLY_REBALANCE
            )

        else:
            status = FUTURE_INVALID

    else:
        if (
            feed_cutoff_local
            == current_month_cutoff
        ):
            status = CURRENT

        elif (
            feed_cutoff_local
            < current_month_cutoff
        ):
            status = (
                STALE_MISSING_MONTHLY_REBALANCE
            )

        else:
            status = FUTURE_INVALID

    expected_cutoff = (
        previous_cutoff
        if now_local
        < current_month_cutoff
        else current_month_cutoff
    )

    return FeedCalendarState(
        status=status,
        feed_cutoff_utc=feed_cutoff_utc,
        feed_cutoff_local=feed_cutoff_local,
        expected_cutoff_local=(
            expected_cutoff
        ),
        previous_cutoff_local=(
            previous_cutoff
        ),
        grace_deadline_local=(
            grace_deadline
        ),
    )
