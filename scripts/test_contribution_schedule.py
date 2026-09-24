from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from src.contributions.contribution_schedule import (
    resolve_weekly_period,
)


kwargs = {
    "timezone_name":
        "America/Mexico_City",
    "weekday":
        "MONDAY",
    "time_local":
        "09:00",
    "start_date_local":
        "2026-09-28",
}


# Before project contribution start.
period = resolve_weekly_period(
    now_utc=datetime(
        2026, 9, 23, 12, 0,
        tzinfo=timezone.utc,
    ),
    **kwargs,
)

assert period is None


# Monday, one minute before 09:00 CDMX.
period = resolve_weekly_period(
    now_utc=datetime(
        2026, 9, 28, 14, 59,
        tzinfo=timezone.utc,
    ),
    **kwargs,
)

assert period is not None
assert period.period_id == "2026-W40"
assert not period.is_due


# Monday exactly at 09:00 CDMX.
period = resolve_weekly_period(
    now_utc=datetime(
        2026, 9, 28, 15, 0,
        tzinfo=timezone.utc,
    ),
    **kwargs,
)

assert period is not None
assert period.period_id == "2026-W40"
assert period.is_due
assert (
    period.scheduled_utc.isoformat()
    == "2026-09-28T15:00:00+00:00"
)


# Later in same week remains same period.
period = resolve_weekly_period(
    now_utc=datetime(
        2026, 10, 1, 18, 0,
        tzinfo=timezone.utc,
    ),
    **kwargs,
)

assert period.period_id == "2026-W40"
assert period.is_due


# Following Monday creates next period.
period = resolve_weekly_period(
    now_utc=datetime(
        2026, 10, 5, 15, 0,
        tzinfo=timezone.utc,
    ),
    **kwargs,
)

assert period.period_id == "2026-W41"
assert period.is_due


print(
    "Contribution schedule test: OK"
)
print(
    "First period : 2026-W40"
)
print(
    "Scheduled    : "
    "2026-09-28 09:00 "
    "America/Mexico_City"
)
print(
    "UTC          : "
    "2026-09-28T15:00:00+00:00"
)
print(
    "No backfill before start date: OK"
)
