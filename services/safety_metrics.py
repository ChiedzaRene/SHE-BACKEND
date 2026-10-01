"""TRIR / LTIFR calculation. The single source of truth: every endpoint uses this.

Definitions (ISO 45001 style reporting, 200,000-hour basis):
  * Recordable incident   = an incident of type "injury"
  * Lost-time injury      = a recordable incident with lost_time_days > 0
  * TRIR  = recordable incidents  x 200,000 / hours worked
  * LTIFR = lost-time injuries    x 200,000 / hours worked

Hours worked come from the monthly `site_hours` entries. Only months with hours entered
count, for the incidents as well as the hours, so a month nobody has reported yet can't
inflate the rate. A site with no hours in the window has rate None, not a made-up number.
"""
from datetime import date
from typing import Dict, Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.incident import Incident
from models.site_hours import SiteHours

RATE_BASIS_HOURS = 200_000
PERIODS = ("12m", "ytd")


def month_start(d: date) -> date:
    return d.replace(day=1)


def window_start(period: str, today: Optional[date] = None) -> date:
    today = today or date.today()
    if period == "ytd":
        return date(today.year, 1, 1)
    # "12m": the current month plus the 11 before it
    months = today.year * 12 + (today.month - 1) - 11
    return date(months // 12, months % 12 + 1, 1)


def _rate(count: int, hours: float) -> Optional[float]:
    return round(count * RATE_BASIS_HOURS / hours, 2) if hours > 0 else None


def _empty() -> dict:
    return {
        "total_incidents": 0,
        "recordable_incidents": 0,
        "lost_time_injuries": 0,
        "hours_worked": 0.0,
        "months_reported": 0,
    }


def _finish(stats: dict) -> dict:
    stats["hours_reported"] = stats["hours_worked"] > 0
    stats["trir"] = _rate(stats["recordable_incidents"], stats["hours_worked"])
    stats["ltifr"] = _rate(stats["lost_time_injuries"], stats["hours_worked"])
    return stats


def compute_by_site(
    db: Session,
    site_ids: Optional[Iterable[int]] = None,
    period: str = "12m",
    today: Optional[date] = None,
) -> Dict[int, dict]:
    """Per-site stats for the window. Every requested site appears, even with no data."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    today = today or date.today()
    start = window_start(period, today)
    site_ids = list(site_ids) if site_ids is not None else None

    hours_q = db.query(SiteHours.site_id, SiteHours.period, SiteHours.hours_worked).filter(
        SiteHours.period >= start, SiteHours.period <= today
    )
    when = func.coalesce(Incident.occurred_at, Incident.date_time)
    inc_q = db.query(Incident.site_id, when, Incident.type, Incident.lost_time_days).filter(
        when >= start
    )
    if site_ids is not None:
        hours_q = hours_q.filter(SiteHours.site_id.in_(site_ids))
        inc_q = inc_q.filter(Incident.site_id.in_(site_ids))

    result: Dict[int, dict] = {sid: _empty() for sid in (site_ids or [])}
    reported = set()  # (site_id, first-of-month) pairs that have hours entered
    for site_id, period_date, hours in hours_q:
        stats = result.setdefault(site_id, _empty())
        if hours > 0:
            reported.add((site_id, period_date))
            stats["hours_worked"] += hours
            stats["months_reported"] += 1

    for site_id, ts, inc_type, lost_days in inc_q:
        stats = result.setdefault(site_id, _empty())
        stats["total_incidents"] += 1
        if (site_id, month_start(ts.date() if hasattr(ts, "date") else ts)) not in reported:
            continue
        if (inc_type or "").strip().lower() == "injury":
            stats["recordable_incidents"] += 1
            if lost_days and lost_days > 0:
                stats["lost_time_injuries"] += 1

    return {sid: _finish(stats) for sid, stats in result.items()}


def combine(per_site: Iterable[dict]) -> dict:
    """Roll sites up into one total. Sites without hours add nothing to either side."""
    total = _empty()
    for s in per_site:
        total["total_incidents"] += s["total_incidents"]
        if s["hours_worked"] > 0:
            for key in ("recordable_incidents", "lost_time_injuries", "hours_worked", "months_reported"):
                total[key] += s[key]
    return _finish(total)
