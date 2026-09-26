from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import (
    date,
    datetime,
    time,
    timedelta,
)
from pathlib import Path
from zoneinfo import ZoneInfo


NOT_DUE = "NOT_DUE"
WAITING_FOR_SOURCE = "WAITING_FOR_SOURCE"
READY_TO_IMPORT = "READY_TO_IMPORT"
MISSING_AFTER_GRACE = "MISSING_AFTER_GRACE"


@dataclass(frozen=True)
class FeedBridgeExpectation:
    cutoff_date: date
    scheduled_local: datetime
    grace_deadline_local: datetime
    expected_filename: str
    expected_source_path: Path
    status: str


def last_calendar_day(
    year: int,
    month: int,
) -> date:

    last_day = monthrange(
        year,
        month,
    )[1]

    return date(
        year,
        month,
        last_day,
    )


def parse_local_time(
    value: str,
) -> time:

    parts = value.split(":")

    if len(parts) != 2:
        raise ValueError(
            "time_local must use HH:MM."
        )

    hour = int(parts[0])
    minute = int(parts[1])

    return time(
        hour=hour,
        minute=minute,
    )


def resolve_feed_bridge_expectation(
    *,
    now_utc: datetime,
    timezone_name: str,
    time_local: str,
    grace_minutes: int,
    source_directory: str | Path,
    filename_template: str,
    source_exists: bool,
) -> FeedBridgeExpectation:

    if (
        now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        raise ValueError(
            "now_utc must be timezone-aware."
        )

    if grace_minutes < 0:
        raise ValueError(
            "grace_minutes cannot be negative."
        )

    if "{cutoff_date}" not in filename_template:
        raise ValueError(
            "filename_template must contain "
            "{cutoff_date}."
        )

    timezone = ZoneInfo(
        timezone_name
    )

    now_local = now_utc.astimezone(
        timezone
    )

    cutoff_date = last_calendar_day(
        now_local.year,
        now_local.month,
    )

    scheduled_local = datetime.combine(
        cutoff_date,
        parse_local_time(
            time_local
        ),
        tzinfo=timezone,
    )

    grace_deadline_local = (
        scheduled_local
        + timedelta(
            minutes=grace_minutes
        )
    )

    expected_filename = (
        filename_template.format(
            cutoff_date=(
                cutoff_date.isoformat()
            )
        )
    )

    expected_source_path = (
        Path(source_directory)
        / expected_filename
    )

    if now_local < scheduled_local:

        status = NOT_DUE

    elif source_exists:

        status = READY_TO_IMPORT

    elif now_local < grace_deadline_local:

        status = WAITING_FOR_SOURCE

    else:

        status = MISSING_AFTER_GRACE

    return FeedBridgeExpectation(
        cutoff_date=cutoff_date,
        scheduled_local=scheduled_local,
        grace_deadline_local=(
            grace_deadline_local
        ),
        expected_filename=(
            expected_filename
        ),
        expected_source_path=(
            expected_source_path
        ),
        status=status,
    )
