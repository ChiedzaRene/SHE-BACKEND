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
# Warning thresholds per 200,000 hours (the dashboards and reports flag sites above these)
TRIR_LIMIT = 1.5
LTIFR_LIMIT = 0.5
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
        # Injuries left out of the rates because their month has no hours entered yet,
        # so the dashboard can say so instead of quietly showing N/A or 0.00
        "uncounted_injuries": 0,
        "months_missing_hours": [],
    }


def _finish(stats: dict) -> dict:
    stats["months_missing_hours"] = sorted(stats["months_missing_hours"])
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
    """Per-site stats for a rolling window. Every requested site appears, even with no data."""
    if period not in PERIODS:
        raise ValueError(f"period must be one of {PERIODS}")
    today = today or date.today()
    return compute_range(db, site_ids, window_start(period, today), None, today)


def compute_range(
    db: Session,
    site_ids: Optional[Iterable[int]],
    start: date,
    end: Optional[date] = None,
    today: Optional[date] = None,
) -> Dict[int, dict]:
    """Per-site stats for whole calendar months from `start` (inclusive) up to `end` (exclusive).

    With no `end` the window runs to today.
    """
    today = today or date.today()
    site_ids = list(site_ids) if site_ids is not None else None

    hours_q = db.query(SiteHours.site_id, SiteHours.period, SiteHours.hours_worked).filter(
        SiteHours.period >= start
    )
    when = func.coalesce(Incident.occurred_at, Incident.date_time)
    inc_q = db.query(Incident.site_id, when, Incident.type, Incident.lost_time_days).filter(
        when >= start
    )
    if end is None:
        hours_q = hours_q.filter(SiteHours.period <= today)
    else:
        hours_q = hours_q.filter(SiteHours.period < end)
        inc_q = inc_q.filter(when < end)
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
        is_injury = (inc_type or "").strip().lower() == "injury"
        month = month_start(ts.date() if hasattr(ts, "date") else ts)
        if (site_id, month) not in reported:
            if is_injury:
                stats["uncounted_injuries"] += 1
                label = month.strftime("%Y-%m")
                if label not in stats["months_missing_hours"]:
                    stats["months_missing_hours"].append(label)
            continue
        if is_injury:
            stats["recordable_incidents"] += 1
            if lost_days and lost_days > 0:
                stats["lost_time_injuries"] += 1

    return {sid: _finish(stats) for sid, stats in result.items()}


def combine(per_site: Iterable[dict]) -> dict:
    """Roll sites up into one total. Sites without hours add nothing to either side."""
    total = _empty()
    for s in per_site:
        total["total_incidents"] += s["total_incidents"]
        total["uncounted_injuries"] += s.get("uncounted_injuries", 0)
        for m in s.get("months_missing_hours", []):
            if m not in total["months_missing_hours"]:
                total["months_missing_hours"].append(m)
        if s["hours_worked"] > 0:
            for key in ("recordable_incidents", "lost_time_injuries", "hours_worked", "months_reported"):
                total[key] += s[key]
    return _finish(total)
