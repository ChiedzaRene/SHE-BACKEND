"""Report builders. Each returns one structured document:

    {"kind", "title", "subtitle", "generated_at", "kpis": [{label, value}],
     "tables": [{"title", "columns": [...], "rows": [[...]]}], "notes": [...]}

The same document is shown on screen (JSON), exported to CSV and rendered to PDF, so the
three can never disagree. Rates come from services.safety_metrics (200,000-hour basis).
"""
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.audit import Audit
from models.corrective_action import CorrectiveAction
from models.incident import Incident
from models.inspections import Inspection
from models.site_licence import SiteLicence
from models.site import Site
from models.training import Training
from services.licences import LICENCE_TYPES, status_of
from services.richtext import as_text
from services.settings import get_safety_limits
from services.safety_metrics import (
    combine,
    compute_range,
    month_start,
    window_start,
)

NA = "N/A"
LICENCE_STATUS = {"expired": "Expired", "missing": "Not recorded", "due_1_month": "Due within a month",
                  "due_3_months": "Due within 3 months"}
MAX_REGISTER_ROWS = 5000
ACTION_DONE = ("resolved", "closed")


class ReportError(ValueError):
    """Bad report parameters; the router turns this into a 422."""


def _rate(value) -> str:
    return NA if value is None else f"{value:.2f}"


def _num(value) -> str:
    return f"{value:,.0f}"


def _day(value) -> str:
    return value.strftime("%Y-%m-%d") if value else ""


def _site_names(db: Session, site_ids=None) -> dict:
    query = db.query(Site.id, Site.name)
    if site_ids is not None:
        query = query.filter(Site.id.in_(list(site_ids)))
    return {sid: name for sid, name in query.order_by(Site.name)}


def _scope(db: Session, site_id: Optional[int]):
    """Returns (site_ids, label). site_id None means every site."""
    if site_id is None:
        names = _site_names(db)
        return list(names), "All sites"
    row = db.query(Site.name).filter(Site.id == site_id).first()
    if not row:
        raise ReportError("Site not found")
    return [site_id], row[0]


def _doc(kind, title, subtitle, kpis, tables, notes=None) -> dict:
    return {
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "kpis": [{"label": k, "value": str(v)} for k, v in kpis],
        "tables": tables,
        "notes": notes or [],
    }


def _status(stats: dict, limits: dict) -> str:
    if stats["ltifr"] is None:
        return "No hours data"
    over = stats["ltifr"] > limits["ltifr_limit"]
    return "Action required" if over else "Within limits"


def _action_counts(db: Session, site_ids, today: datetime) -> dict:
    """Snapshot of corrective actions (not period-bound: an open action is open today)."""
    query = db.query(CorrectiveAction.site_id, CorrectiveAction.status, CorrectiveAction.due_date)
    if site_ids is not None:
        query = query.filter(CorrectiveAction.site_id.in_(list(site_ids)))
    per_site: dict = {}
    for site_id, status, due in query:
        c = per_site.setdefault(site_id, {"open": 0, "overdue": 0, "done": 0})
        if (status or "").lower() in ACTION_DONE:
            c["done"] += 1
        else:
            c["open"] += 1
            if due and due < today:
                c["overdue"] += 1
    return per_site


def parse_month(month: Optional[str], today: Optional[date] = None) -> date:
    today = today or date.today()
    if not month:  # default: last full month, the one being reported on
        return (month_start(today) - timedelta(days=1)).replace(day=1)
    try:
        year, mon = (int(p) for p in month.split("-"))
        first = date(year, mon, 1)
    except (ValueError, TypeError):
        raise ReportError("month must be YYYY-MM")
    if first > month_start(today):
        raise ReportError("Cannot report on a future month")
    return first


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


# ─── 1. Monthly SHE performance ─────────────────────────────────────────────

def performance_report(db: Session, site_id: Optional[int], month: Optional[str]) -> dict:
    first = parse_month(month)
    nxt = _add_months(first, 1)
    site_ids, scope = _scope(db, site_id)
    names = _site_names(db, site_ids)

    this_month = compute_range(db, site_ids, first, nxt)
    rolling = compute_range(db, site_ids, _add_months(first, -11), nxt)
    m, r = combine(this_month.values()), combine(rolling.values())

    when = func.coalesce(Incident.occurred_at, Incident.date_time)
    incidents = (
        db.query(Incident.type, Incident.severity)
        .filter(when >= first, when < nxt, Incident.site_id.in_(site_ids))
        .all()
    )
    actions = _action_counts(db, site_ids, datetime.now())
    open_a = sum(a["open"] for a in actions.values())
    overdue = sum(a["overdue"] for a in actions.values())

    kpis = [
        ("Hours worked", _num(m["hours_worked"]) if m["hours_reported"] else NA),
        ("LTIFR (month)", _rate(m["ltifr"])),
        ("LTIFR (rolling 12 mo)", _rate(r["ltifr"])),
        ("Incidents logged", len(incidents)),
        ("Open corrective actions", open_a),
        ("Overdue actions", overdue),
    ]

    sev_order = ["critical", "high", "medium", "low"]
    by_type = Counter((t or "other").lower() for t, _ in incidents)
    by_sev = Counter((s or "").lower() for _, s in incidents)
    tables = [
        {"title": "Incidents by type", "columns": ["Type", "Count"],
         "rows": [[k.title(), v] for k, v in sorted(by_type.items(), key=lambda kv: -kv[1])]},
        {"title": "Incidents by severity", "columns": ["Severity", "Count"],
         "rows": [[k.title(), by_sev[k]] for k in sev_order if by_sev[k]]},
    ]
    if site_id is None:
        rows = []
        for sid, name in names.items():
            s = this_month[sid]
            a = actions.get(sid, {"open": 0, "overdue": 0})
            rows.append([name, _num(s["hours_worked"]) if s["hours_reported"] else NA,
                         s["recordable_incidents"], s["lost_time_injuries"],
                         _rate(s["ltifr"]), a["open"], a["overdue"]])
        tables.append({"title": "Sites this month",
                       "columns": ["Site", "Hours", "Recordable", "Lost-time", "LTIFR",
                                   "Open actions", "Overdue"],
                       "rows": rows})
    notes = [
        "LTIFR is per 200,000 hours worked. Recordable = injury incidents; "
        "lost-time = injuries with lost days. Only months with hours entered are counted.",
    ]
    if not m["hours_reported"]:
        notes.append("No hours worked have been entered for this month, so its rates show N/A.")
    return _doc("performance", "Monthly SHE Performance Report",
                f"{scope} · {first.strftime('%B %Y')}", kpis, tables, notes)


# ─── 2. Compliance status ───────────────────────────────────────────────────

def compliance_report(db: Session, site_id: Optional[int]) -> dict:
    site_ids, scope = _scope(db, site_id)
    names = _site_names(db, site_ids)

    audits: dict = {}
    for sid, score, status, d in db.query(Audit.site_id, Audit.score, Audit.status, Audit.date).filter(
            Audit.site_id.in_(site_ids)):
        a = audits.setdefault(sid, {"n": 0, "sum": 0.0, "open": 0, "last": None})
        a["n"] += 1
        a["sum"] += score or 0
        if (status or "open").lower() not in ("completed", "closed"):
            a["open"] += 1
        if d and (a["last"] is None or d > a["last"]):
            a["last"] = d

    inspections: dict = {}
    for sid, score in db.query(Inspection.site_id, Inspection.overall_score).filter(
            Inspection.site_id.in_(site_ids)):
        i = inspections.setdefault(sid, [0, 0.0])
        i[0] += 1
        i[1] += score or 0

    trainings: dict = {}
    for sid, trained, total in db.query(Training.site_id, Training.trained_employees,
                                        Training.total_employees).filter(Training.site_id.in_(site_ids)):
        t = trainings.setdefault(sid, [0, 0, 0])
        t[0] += 1
        t[1] += trained or 0
        t[2] += total or 0

    # Licences: every site should hold each type; list the ones expired, missing or due within 3 months
    today = date.today()
    current = {(lic.site_id, lic.licence_type): lic for lic in db.query(SiteLicence).filter(
        SiteLicence.site_id.in_(site_ids), SiteLicence.superseded_by.is_(None))}
    licence_rows, bad, expiring = [], 0, 0
    for sid, name in names.items():
        for key, (lic_name, _issuer) in LICENCE_TYPES.items():
            lic = current.get((sid, key))
            status = status_of(lic.expiry_date if lic else None, today)
            if status in ("expired", "missing"):
                bad += 1
            elif status != "valid":
                expiring += 1
            if status != "valid":
                licence_rows.append([name, lic_name, LICENCE_STATUS[status],
                                     _day(lic.expiry_date) if lic else "",
                                     (lic.expiry_date - today).days if lic else ""])
    licence_rows.sort(key=lambda r: (r[4] == "", r[4] if r[4] != "" else 0))

    all_audits = [a for a in audits.values()]
    n_audits = sum(a["n"] for a in all_audits)
    avg_audit = sum(a["sum"] for a in all_audits) / n_audits if n_audits else None
    t_trained = sum(t[1] for t in trainings.values())
    t_total = sum(t[2] for t in trainings.values())
    kpis = [
        ("Audits on record", n_audits),
        ("Average audit score", NA if avg_audit is None else f"{avg_audit:.1f}"),
        ("Open audits", sum(a["open"] for a in all_audits)),
        ("Licences: expired / not recorded", bad),
        ("Licences: due within 3 months", expiring),
        ("Training coverage", NA if not t_total else f"{100 * t_trained / t_total:.0f}%"),
    ]
    site_rows = []
    for sid, name in names.items():
        a = audits.get(sid)
        i = inspections.get(sid)
        t = trainings.get(sid)
        site_rows.append([
            name,
            a["n"] if a else 0,
            f"{a['sum'] / a['n']:.1f}" if a else NA,
            a["open"] if a else 0,
            _day(a["last"]) if a else "",
            f"{i[1] / i[0]:.1f}" if i else NA,
            f"{100 * t[1] / t[2]:.0f}%" if t and t[2] else NA,
        ])
    tables = [
        {"title": "Audits, inspections and training by site",
         "columns": ["Site", "Audits", "Avg score", "Open", "Last audit", "Avg inspection %", "Training coverage"],
         "rows": site_rows},
        {"title": "Licences needing attention",
         "columns": ["Site", "Licence", "Status", "Due", "Days left"],
         "rows": licence_rows},
    ]
    return _doc("compliance", "Compliance Status Report",
                f"{scope} · as of {date.today().isoformat()}", kpis, tables,
                ["Licences are listed when expired, not recorded or due within 3 months. "
                 "A negative 'Days left' means the licence has already expired."])


# ─── 3. Incident register ───────────────────────────────────────────────────

def incident_register(db: Session, site_id: Optional[int], start: Optional[date], end: Optional[date],
                      inc_type: Optional[str], severity: Optional[str]) -> dict:
    end = end or date.today()
    start = start or (end - timedelta(days=90))
    if start > end:
        raise ReportError("start must be on or before end")
    site_ids, scope = _scope(db, site_id)
    names = _site_names(db, site_ids)

    when = func.coalesce(Incident.occurred_at, Incident.date_time)
    query = db.query(Incident, when.label("when")).filter(
        Incident.site_id.in_(site_ids), when >= start, when < end + timedelta(days=1))
    if inc_type:
        query = query.filter(func.lower(Incident.type) == inc_type.lower())
    if severity:
        query = query.filter(func.lower(Incident.severity) == severity.lower())
    total = query.count()
    rows_q = query.order_by(when.desc()).limit(MAX_REGISTER_ROWS).all()

    rows = [[inc.id, names.get(inc.site_id, ""), when_val.strftime("%Y-%m-%d %H:%M") if when_val else "",
             (inc.type or "").title(), inc.injured_person or "", (inc.severity or "").title(),
             inc.lost_time_days or 0, "Yes" if inc.resolved else "No", as_text(inc.description)]
            for inc, when_val in rows_q]
    injuries = sum(1 for r in rows if r[3].lower() == "injury")
    kpis = [("Incidents", total), ("Injuries", injuries),
            ("With lost time", sum(1 for r in rows if r[6] > 0)),
            ("Resolved", sum(1 for r in rows if r[7] == "Yes"))]
    notes = []
    if total > MAX_REGISTER_ROWS:
        notes.append(f"Showing the most recent {MAX_REGISTER_ROWS} of {total} incidents; narrow the dates.")
    filters = [f for f in (f"type: {inc_type}" if inc_type else "", f"severity: {severity}" if severity else "") if f]
    subtitle = f"{scope} · {start.isoformat()} to {end.isoformat()}" + (f" · {', '.join(filters)}" if filters else "")
    return _doc("incidents", "Incident Register", subtitle, kpis,
                [{"title": "Incidents",
                  "columns": ["ID", "Site", "Occurred", "Type", "Injured person", "Severity", "Lost days", "Resolved",
                              "Description"],
                  "rows": rows}], notes)


# ─── 4. Site comparison / leaderboard ───────────────────────────────────────

def leaderboard_report(db: Session, period: str) -> dict:
    if period not in ("12m", "ytd"):
        raise ReportError("period must be 12m or ytd")
    names = _site_names(db)
    limits = get_safety_limits(db)
    stats = compute_range(db, list(names), window_start(period), None)
    actions = _action_counts(db, list(names), datetime.now())
    total = combine(stats.values())

    # Best (lowest LTIFR, then fewest injuries) first; sites without hours data go last so they can't look "best"
    order = sorted(names, key=lambda sid: (stats[sid]["ltifr"] is None, stats[sid]["ltifr"] or 0,
                                           stats[sid]["recordable_incidents"], names[sid]))
    rows = []
    for rank, sid in enumerate(order, 1):
        s = stats[sid]
        a = actions.get(sid, {"open": 0, "overdue": 0})
        rows.append([rank if s["ltifr"] is not None else "", names[sid],
                     _num(s["hours_worked"]) if s["hours_reported"] else NA,
                     s["recordable_incidents"], s["lost_time_injuries"],
                     _rate(s["ltifr"]), a["open"], a["overdue"], _status(s, limits)])
    flagged = sum(1 for sid in names if _status(stats[sid], limits) == "Action required")
    label = "Rolling 12 months" if period == "12m" else f"Year to date {date.today().year}"
    kpis = [("Sites", len(names)), ("Sites reporting hours", sum(1 for s in stats.values() if s["hours_reported"])),
            ("Group LTIFR", _rate(total["ltifr"])),
            ("Sites needing action", flagged)]
    return _doc("leaderboard", "Site Comparison", label, kpis,
                [{"title": "Ranked by LTIFR (lowest first)",
                  "columns": ["Rank", "Site", "Hours", "Recordable", "Lost-time", "LTIFR",
                              "Open actions", "Overdue", "Status"],
                  "rows": rows}],
                [f"Limit: LTIFR {limits['ltifr_limit']:g} per 200,000 hours. Sites with no hours "
                 "entered are listed last, unranked."])
