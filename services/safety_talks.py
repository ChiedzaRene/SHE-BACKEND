"""Weekly toolbox talks: when they can be submitted, which weeks count, and who is told about missed ones.

Rules
  * Every site gives a talk each Monday. Its manager submits it (title, people present, a document)
    from Monday until the end of Tuesday, local time. After that the week is closed for good.
  * A week counts towards a site's completion rate once its window has closed, or as soon as the talk
    is in (so submitting early never lowers the rate, and an open week never counts as missed).
  * Weeks are counted from when tracking began (the first deploy with this feature), or from when the
    site was added if that is later.
  * When a week closes without a talk, the SHE team, the admins and the site's manager are told once.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from models.app_setting import AppSetting
from models.safety_talk import SafetyTalk, SafetyTalkMiss
from models.site import Site
from models.user import User
from services.clock import LOCAL_TZ, local_today
from services.notifications import notify, site_managers, team

START_KEY = "safety_talks_start"


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def deadline_of(week_of: date) -> datetime:
    """The end of the Tuesday after the talk's Monday, local time."""
    return datetime.combine(week_of + timedelta(days=1), time(23, 59, 59), tzinfo=LOCAL_TZ)


def open_week(today: date) -> Optional[date]:
    """The week whose talk can be submitted today: Monday and Tuesday only."""
    return monday_of(today) if today.weekday() in (0, 1) else None


def next_open(today: date) -> date:
    """The Monday the next submission window opens (today when it is Monday)."""
    return today + timedelta(days=(7 - today.weekday()) % 7)


def is_closed(week_of: date, today: date) -> bool:
    return today > week_of + timedelta(days=1)


def tracking_start(db: Session, today: Optional[date] = None) -> date:
    """The day weekly talks started being tracked: stored the first time it is asked for."""
    row = db.query(AppSetting).filter(AppSetting.key == START_KEY).first()
    if row:
        try:
            return date.fromisoformat(row.value)
        except ValueError:
            pass
    start = today or local_today()
    if row:
        row.value = start.isoformat()
    else:
        db.add(AppSetting(key=START_KEY, value=start.isoformat()))
    db.commit()
    return start


def _mondays(start: date, end: date) -> List[date]:
    """Mondays on or after `start` and before `end`."""
    d = start + timedelta(days=(7 - start.weekday()) % 7)
    out = []
    while d < end:
        out.append(d)
        d += timedelta(days=7)
    return out


def site_start(site: Site, tracked_from: date) -> date:
    return max(tracked_from, site.talks_from) if site.talks_from else tracked_from


def weeks_status(db: Session, sites: Iterable[Site], start: date, end: date, today: date) -> Dict[int, dict]:
    """Per site, between `start` and `end` (exclusive): the weeks due, done and missed, and this week's state."""
    sites = list(sites)
    tracked_from = tracking_start(db, today)
    submitted = defaultdict(set)
    if sites:
        for site_id, week in (
            db.query(SafetyTalk.site_id, SafetyTalk.week_of)
            .filter(SafetyTalk.site_id.in_([s.id for s in sites]), SafetyTalk.week_of >= start - timedelta(days=7),
                    SafetyTalk.week_of < end)
            .all()
        ):
            submitted[site_id].add(week)
    current = open_week(today)
    out = {}
    for site in sites:
        first = max(start, site_start(site, tracked_from))
        weeks = [m for m in _mondays(first, min(end, today + timedelta(days=1)))]
        done = [m for m in weeks if m in submitted[site.id]]
        missed = [m for m in weeks if is_closed(m, today) and m not in submitted[site.id]]
        due = len(done) + len(missed)
        out[site.id] = {
            "due": due,
            "done": len(done),
            "missed_weeks": [m.isoformat() for m in sorted(missed, reverse=True)],
            "rate": round(100 * len(done) / due, 1) if due else None,
            "this_week_open": bool(current and current in weeks),
            "this_week_done": bool(current and current in submitted[site.id]),
        }
    return out


def combined_rate(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    due = sum(r["due"] for r in rows)
    done = sum(r["done"] for r in rows)
    return {"due": due, "done": done, "missed": due - done, "rate": round(100 * done / due, 1) if due else None}


def record_missed(db: Session, today: Optional[date] = None) -> int:
    """Tell people about every week that has closed without a talk (each site and week only once)."""
    today = today or local_today()
    tracked_from = tracking_start(db, today)
    last_closed = monday_of(today) - timedelta(days=7) if today.weekday() in (0, 1) else monday_of(today)
    told = 0
    sites = db.query(Site).all()
    if not sites:
        return 0
    already = {(m.site_id, m.week_of) for m in db.query(SafetyTalkMiss).all()}
    talks = {(t.site_id, t.week_of) for t in db.query(SafetyTalk.site_id, SafetyTalk.week_of).all()}
    for site in sites:
        # only look back four weeks: older gaps were dealt with by earlier runs
        first = max(site_start(site, tracked_from), last_closed - timedelta(days=28))
        for week in _mondays(first, last_closed + timedelta(days=1)):
            if (site.id, week) in talks or (site.id, week) in already:
                continue
            db.add(SafetyTalkMiss(site_id=site.id, week_of=week))
            db.commit()
            when = week.strftime("%a %d %b").replace(" 0", " ")
            managers = site_managers(db, site.id)
            who_runs = ", ".join(m.full_name or m.email for m in managers) or "no site manager assigned"
            notify(db, team(db), kind="talk_missed", title=f"Missed toolbox talk: {site.name} ({when})",
                   message=f"No talk was submitted for the week of {when} ({who_runs}).",
                   link="/trainings", resource="safety_talks", resource_id=None)
            notify(db, managers, kind="talk_missed", title=f"Your toolbox talk for {when} was not submitted",
                   message="Submissions close at the end of Tuesday. This week counts as missed.",
                   link="/trainings", resource="safety_talks", resource_id=None)
            told += 1
    return told


def manager_names(db: Session, site_ids: List[int]) -> Dict[int, List[str]]:
    out = defaultdict(list)
    if site_ids:
        for u in db.query(User).filter(User.role == "site_manager", User.site_id.in_(site_ids), User.is_active.is_(True)):
            out[u.site_id].append(u.full_name or u.email)
    return out
