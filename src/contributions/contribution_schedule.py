from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ContributionPeriod:
    period_id: str
    scheduled_local: datetime
    scheduled_utc: datetime
    is_due: bool


def resolve_weekly_period(
    *,
    now_utc: datetime,
    timezone_name: str,
    weekday: str,
    time_local: str,
    start_date_local: str,
) -> ContributionPeriod | None:

    tz = ZoneInfo(timezone_name)

    if now_utc.tzinfo is None:
        raise ValueError(
            "now_utc must be timezone-aware."
        )

    weekday_map = {
        "MONDAY": 0,
        "TUESDAY": 1,
        "WEDNESDAY": 2,
        "THURSDAY": 3,
        "FRIDAY": 4,
        "SATURDAY": 5,
        "SUNDAY": 6,
    }

    target_weekday = weekday_map[
        weekday.upper()
    ]

    local_now = now_utc.astimezone(tz)

    scheduled_date = (
        local_now.date()
        - timedelta(
            days=(
                local_now.weekday()
                - target_weekday
            )
            % 7
        )
    )

    start_date = date.fromisoformat(
        start_date_local
    )

    if scheduled_date < start_date:
        return None

    hh, mm = (
        int(x)
        for x in time_local.split(":")
    )

    scheduled_local = datetime.combine(
        scheduled_date,
        time(
            hour=hh,
            minute=mm,
        ),
        tzinfo=tz,
    )

    iso = scheduled_date.isocalendar()

    return ContributionPeriod(
        period_id=(
            f"{iso.year}-W"
            f"{iso.week:02d}"
        ),
        scheduled_local=scheduled_local,
        scheduled_utc=(
            scheduled_local.astimezone(
                ZoneInfo("UTC")
            )
        ),
        is_due=(
            local_now
            >= scheduled_local
        ),
    )
