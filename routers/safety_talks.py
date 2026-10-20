"""Weekly toolbox talks: site managers submit them; the SHE team tracks submissions across sites."""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session, undefer

from database import get_db
from models.safety_talk import SafetyTalk
from models.site import Site
from models.user import User
from services.access import assert_site_access
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role
from services.clock import local_today
from services.dashboard import PERIODS, period_range
from services.files import clean_filename, file_response, is_viewable, read_upload
from services.notifications import short
from services.safety_talks import (
    combined_rate, deadline_of, manager_names, next_open, open_week, record_missed, tracking_start, weeks_status,
)

router = APIRouter(prefix="/safety-talks", tags=["Toolbox talks"])


def _talk_out(t: SafetyTalk, sites: dict, names: dict) -> dict:
    site = sites.get(t.site_id)
    return {
        "id": t.id, "site_id": t.site_id, "site_name": site.name if site else None,
        "region": site.region if site else None, "week_of": t.week_of.isoformat(), "title": t.title,
        "attendees": t.attendees, "notes": t.notes, "filename": t.filename, "content_type": t.content_type,
        "size": t.size, "can_view": is_viewable(t.filename),
        "submitted_by_name": names.get(t.submitted_by, "Someone"),
        "submitted_at": t.submitted_at.isoformat() if t.submitted_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _names(db: Session, user_ids) -> dict:
    ids = set(user_ids) or {0}
    return {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_(ids))}


@router.get("/current")
def current_week(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """For a site manager: this week's talk (open or not, deadline, what was sent) and the site's completion rate."""
    today = local_today()
    week = open_week(today)
    out = {
        "today": today.isoformat(),
        "week_of": week.isoformat() if week else None,
        "open": week is not None,
        "deadline": deadline_of(week).isoformat() if week else None,
        "next_open": next_open(today).isoformat() if not week else None,
        "talk": None,
        "cumulative": None,
        "tracking_since": tracking_start(db, today).isoformat(),
    }
    if current_user.role != "site_manager" or not current_user.site_id:
        return out
    site = db.query(Site).filter(Site.id == current_user.site_id).first()
    if not site:
        return out
    if week:
        talk = db.query(SafetyTalk).filter(SafetyTalk.site_id == site.id, SafetyTalk.week_of == week).first()
        if talk:
            out["talk"] = _talk_out(talk, {site.id: site}, _names(db, [talk.submitted_by]))
    status = weeks_status(db, [site], date(2000, 1, 3), today.replace(year=today.year + 1), today)[site.id]
    out["cumulative"] = {k: status[k] for k in ("due", "done", "rate", "missed_weeks")}
    return out


@router.post("/", status_code=201)
async def submit_talk(
    request: Request,
    title: str = Form(..., max_length=200),
    attendees: int = Form(..., ge=1, le=100_000),
    notes: Optional[str] = Form(None, max_length=2000),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("site_manager")),
):
    """Submit (or, until the window closes, replace) this week's talk for the manager's own site."""
    if not current_user.site_id:
        raise HTTPException(status_code=400, detail="Your account isn't linked to a site. Ask an administrator.")
    today = local_today()
    week = open_week(today)
    if not week:
        raise HTTPException(
            status_code=409,
            detail=f"Talks can only be submitted on Monday and Tuesday. The next window opens on "
                   f"{next_open(today).strftime('%A %d %B').replace(' 0', ' ')}.",
        )
    title = " ".join(title.split())
    if not title:
        raise HTTPException(status_code=422, detail="Give the talk a title.")
    filename, content_type = clean_filename(file)
    data = await read_upload(file)

    talk = db.query(SafetyTalk).filter(SafetyTalk.site_id == current_user.site_id, SafetyTalk.week_of == week).first()
    replaced = talk is not None
    if not talk:
        talk = SafetyTalk(site_id=current_user.site_id, week_of=week, submitted_by=current_user.id)
        db.add(talk)
    else:
        talk.submitted_by = current_user.id
        talk.updated_at = datetime.now(timezone.utc)
    talk.title, talk.attendees, talk.notes = title, attendees, (notes or "").strip() or None
    talk.filename, talk.content_type, talk.size, talk.data = filename, content_type, len(data), data
    db.commit()
    db.refresh(talk)
    log_action(db=db, user=current_user, action="SUBMIT_SAFETY_TALK", resource="safety_talks", resource_id=talk.id,
               details=f"{'Replaced' if replaced else 'Submitted'} the talk for the week of {week.isoformat()}: "
                       f"\"{short(title, 80)}\", {attendees} present ({filename})",
               ip_address=request.client.host if request.client else None)
    site = db.query(Site).filter(Site.id == talk.site_id).first()
    return _talk_out(talk, {site.id: site}, {current_user.id: current_user.full_name or current_user.email})


@router.get("/overview")
def overview(
    period: str = Query("month", description="month, last_month, quarter, last_quarter, 3m, 6m, ytd or 12m"),
    site_id: Optional[int] = Query(None, gt=0),
    region: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every site's submissions for a period: completion rates, missed weeks, this week's stragglers and the talks."""
    if period not in PERIODS:
        raise HTTPException(status_code=422, detail=f"period must be one of: {', '.join(PERIODS)}")
    today = local_today()
    record_missed(db, today)  # nobody waits on the hourly check to see a week that has just closed

    all_sites = db.query(Site).order_by(Site.name).all()
    regions = sorted({s.region for s in all_sites if s.region})
    if current_user.role == "site_manager":
        site_id, region = current_user.site_id, None
    sites = [s for s in all_sites if (not site_id or s.id == site_id) and (not region or s.region == region)]
    if site_id and not sites:
        raise HTTPException(status_code=404, detail="Site not found")

    (start, end), _ = period_range(period, today)
    status = weeks_status(db, sites, start, end, today)
    managers = manager_names(db, [s.id for s in sites])
    rows = []
    for s in sites:
        st = status[s.id]
        rows.append({"site_id": s.id, "name": s.name, "region": s.region, "managers": managers.get(s.id, []),
                     **{k: st[k] for k in ("due", "done", "rate", "missed_weeks", "this_week_open", "this_week_done")}})
    missed = sorted(
        ({"site_id": r["site_id"], "name": r["name"], "region": r["region"], "managers": r["managers"], "week_of": w}
         for r in rows for w in r["missed_weeks"]),
        key=lambda m: (m["week_of"], m["name"]), reverse=True,
    )
    week = open_week(today)
    pending = [{"site_id": r["site_id"], "name": r["name"], "region": r["region"], "managers": r["managers"]}
               for r in rows if week and not r["this_week_done"]]

    talks = (
        db.query(SafetyTalk)
        .filter(SafetyTalk.site_id.in_([s.id for s in sites] or [0]), SafetyTalk.week_of >= start,
                SafetyTalk.week_of < end)
        .order_by(SafetyTalk.week_of.desc(), SafetyTalk.site_id)
        .all()
    )
    names = _names(db, [t.submitted_by for t in talks])
    by_id = {s.id: s for s in sites}
    return {
        "period": period,
        "period_name": PERIODS[period],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "regions": regions,
        "this_week": {
            "week_of": week.isoformat() if week else None,
            "open": week is not None,
            "deadline": deadline_of(week).isoformat() if week else None,
            "pending": pending,
        },
        "totals": {**combined_rate(rows), "sites": len(rows), "attendees": sum(t.attendees for t in talks)},
        "sites": rows,
        "missed": missed,
        "talks": [_talk_out(t, by_id, names) for t in talks],
    }


def _get_talk(db: Session, user: User, talk_id: int) -> SafetyTalk:
    talk = db.query(SafetyTalk).options(undefer(SafetyTalk.data)).filter(SafetyTalk.id == talk_id).first()
    if not talk:
        raise HTTPException(status_code=404, detail="Talk not found")
    assert_site_access(user, talk.site_id)
    return talk


@router.get("/{talk_id}/view")
def view_talk_document(talk_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    talk = _get_talk(db, current_user, talk_id)
    if not is_viewable(talk.filename):
        raise HTTPException(status_code=415, detail="This type of file can't be shown in the app. Download it instead.")
    return file_response(talk.data, talk.content_type, talk.filename, "inline")


@router.get("/{talk_id}/download")
def download_talk_document(talk_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    talk = _get_talk(db, current_user, talk_id)
    return file_response(talk.data, talk.content_type, talk.filename, "attachment")
