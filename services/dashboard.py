"""Figures for the dashboards, for any period and one site or all of them.

Rates are worked out for each site on its own (its injuries over its own hours, per 1,000,000 hours).
The figure for "all sites" is the average of the sites' rates, counting only sites with hours entered.
"""
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.corrective_action import CorrectiveAction
from models.incident import Incident
from models.site import Site
from models.site_hours import SiteHours
from models.user import User
from services.safety_metrics import compute_range
from services.safety_talks import combined_rate, weeks_status

PERIODS = {
    "month": "This month",
    "last_month": "Last month",
    "quarter": "This quarter",
    "last_quarter": "Last quarter",
    "3m": "Last 3 months",
    "6m": "Last 6 months",
    "ytd": "Year to date",
    "12m": "Last 12 months",
}
CLOSED_STATUSES = ("resolved", "closed")


def _add_months(d: date, months: int) -> date:
    m = d.year * 12 + (d.month - 1) + months
    return date(m // 12, m % 12 + 1, 1)


def period_range(key: str, today: Optional[date] = None):
    """[start, end) as whole months, the matching previous period, and labels."""
    if key not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    today = today or date.today()
    this_month = today.replace(day=1)
    quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
    if key == "month":
        start, months = this_month, 1
    elif key == "last_month":
        start, months = _add_months(this_month, -1), 1
    elif key == "quarter":
        start, months = quarter_start, 3
    elif key == "last_quarter":
        start, months = _add_months(quarter_start, -3), 3
    elif key in ("3m", "6m"):
        months = 3 if key == "3m" else 6
        start = _add_months(this_month, 1 - months)
    elif key == "ytd":
        start, months = date(today.year, 1, 1), today.month
    else:  # 12m
        start, months = _add_months(this_month, -11), 12
    end = _add_months(start, months)
    # compare with the same stretch just before; year to date compares with the same months last year
    shift = 12 if key == "ytd" else months
    prev_start, prev_end = _add_months(start, -shift), _add_months(end, -shift)
    return (start, end), (prev_start, prev_end)


def _label(start: date, end: date) -> str:
    last = _add_months(end, -1)
    if start == last:
        return start.strftime("%B %Y")
    same_year = start.year == last.year
    return f"{start:%b}{'' if same_year else start.strftime(' %Y')} – {last:%b %Y}"


def _avg(values) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def _months(start: date, end: date) -> List[date]:
    out, d = [], start
    while d < end:
        out.append(d)
        d = _add_months(d, 1)
    return out


def summarise(db: Session, site_ids: List[int], start: date, end: date, today: Optional[date] = None) -> dict:
    today = today or date.today()
    rates = compute_range(db, site_ids, start, end, today)
    when = func.coalesce(Incident.occurred_at, Incident.date_time)
    end_dt = datetime.combine(end, datetime.min.time())
    start_dt = datetime.combine(start, datetime.min.time())

    # incidents by month and type (for the stacked chart) and by type
    months = _months(start, end)
    by_month = {m.strftime("%Y-%m"): defaultdict(int) for m in months}
    by_type: Dict[str, int] = defaultdict(int)
    per_site_incidents: Dict[int, int] = defaultdict(int)
    for site_id, ts, kind in (
        db.query(Incident.site_id, when, Incident.type)
        .filter(Incident.site_id.in_(site_ids), when >= start_dt, when < end_dt)
        .all()
    ):
        kind = (kind or "other").strip().lower()
        by_type[kind] += 1
        per_site_incidents[site_id] += 1
        key = ts.strftime("%Y-%m")
        if key in by_month:
            by_month[key][kind] += 1

    # corrective actions raised in the period: how many are done, and how long closing took
    actions = defaultdict(lambda: {"total": 0, "completed": 0, "days": []})
    for site_id, status, created, resolved in (
        db.query(CorrectiveAction.site_id, CorrectiveAction.status, CorrectiveAction.created_at,
                 CorrectiveAction.date_resolved)
        .filter(CorrectiveAction.site_id.in_(site_ids),
                CorrectiveAction.created_at >= start_dt, CorrectiveAction.created_at < end_dt)
        .all()
    ):
        a = actions[site_id]
        a["total"] += 1
        if (status or "").lower() in CLOSED_STATUSES:
            a["completed"] += 1
            if created and resolved:
                a["days"].append(max(0.0, (resolved - created).total_seconds() / 86400))

    # hours and headcount entered by the sites (headcount: the latest month in the period)
    workers: Dict[int, int] = {}
    for site_id, period, count in (
        db.query(SiteHours.site_id, SiteHours.period, SiteHours.workers)
        .filter(SiteHours.site_id.in_(site_ids), SiteHours.period >= start, SiteHours.period < end,
                SiteHours.workers.isnot(None))
        .order_by(SiteHours.period)
        .all()
    ):
        workers[site_id] = count

    sites = {s.id: s for s in db.query(Site).filter(Site.id.in_(site_ids)).all()}
    managers = defaultdict(list)
    for m in db.query(User).filter(User.role == "site_manager", User.site_id.in_(site_ids), User.is_active.is_(True)):
        managers[m.site_id].append(m.full_name or m.email)

    talks = weeks_status(db, sites.values(), start, end, today)
    rows = []
    for sid in site_ids:
        r, a, site = rates.get(sid, {}), actions.get(sid), sites.get(sid)
        if site is None:
            continue
        rows.append({
            "site_id": sid,
            "name": site.name,
            "address": site.address,
            "contact_number": site.contact_number,
            "managers": managers.get(sid, []),
            "incidents": per_site_incidents.get(sid, 0),
            "injuries": r.get("recordable_incidents", 0) + r.get("uncounted_injuries", 0),
            "lost_time_injuries": r.get("lost_time_injuries", 0),
            "hours_worked": r.get("hours_worked", 0.0),
            "workers": workers.get(sid),
            "ltifr": r.get("ltifr"),
            "uncounted_injuries": r.get("uncounted_injuries", 0),
            "months_missing_hours": r.get("months_missing_hours", []),
            "actions_total": a["total"] if a else 0,
            "actions_completed": a["completed"] if a else 0,
            "actions_completion_pct": round(100 * a["completed"] / a["total"], 1) if a and a["total"] else None,
            "avg_days_to_close": round(sum(a["days"]) / len(a["days"]), 1) if a and a["days"] else None,
            "region": site.region,
            "talks_due": talks[sid]["due"],
            "talks_done": talks[sid]["done"],
            "talks_rate": talks[sid]["rate"],
        })

    all_days = [d for a in actions.values() for d in a["days"]]
    total_actions = sum(a["total"] for a in actions.values())
    done_actions = sum(a["completed"] for a in actions.values())
    reported = [r for r in rows if r["hours_worked"] > 0]
    talk_totals = combined_rate({"due": r["talks_due"], "done": r["talks_done"]} for r in rows)
    return {
        "start": start.isoformat(),
        "end": _add_months(end, -1).isoformat(),   # first day of the last month included
        "label": _label(start, end),
        "totals": {
            "incidents": sum(by_type.values()),
            "injuries": sum(r["injuries"] for r in rows),
            "lost_time_injuries": sum(r["lost_time_injuries"] for r in rows),
            "hours_worked": sum(r["hours_worked"] for r in rows),
            "workers": sum(r["workers"] for r in rows if r["workers"] is not None) if any(
                r["workers"] is not None for r in rows) else None,
            # average of the sites' own rates (sites without hours left out)
            "ltifr": _avg(r["ltifr"] for r in rows),
            "sites_with_hours": len(reported),
            "sites": len(rows),
            "uncounted_injuries": sum(r["uncounted_injuries"] for r in rows),
            "months_missing_hours": sorted({m for r in rows for m in r["months_missing_hours"]}),
            "actions_total": total_actions,
            "actions_completed": done_actions,
            "actions_completion_pct": round(100 * done_actions / total_actions, 1) if total_actions else None,
            "avg_days_to_close": round(sum(all_days) / len(all_days), 1) if all_days else None,
            # weekly toolbox talks: submitted / weeks due, across the sites shown
            "talks_due": talk_totals["due"],
            "talks_done": talk_totals["done"],
            "talks_rate": talk_totals["rate"],
        },
        "by_type": [{"name": k, "value": v} for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])],
        "by_month": [{"month": k, **dict(v)} for k, v in by_month.items()],
        "sites": rows,
    }
