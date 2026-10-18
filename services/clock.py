"""Local time for rules that follow the working week (e.g. "talks close at the end of Tuesday").

The server runs in UTC, so these use the company's time zone: APP_TIMEZONE, Africa/Harare by default.
"""
import os
from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo(os.getenv("APP_TIMEZONE", "Africa/Harare"))
except Exception:  # noqa: BLE001 - no time zone data on this machine: Harare is UTC+2 all year
    LOCAL_TZ = timezone(timedelta(hours=2), "CAT")


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def local_today() -> date:
    return local_now().date()
