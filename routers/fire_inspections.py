"""Fire equipment inspections the sites submit themselves.

  - Fortnightly: the fire equipment checklist (GP-SHE/OPR/10/02), each item conforming (C), not
    conforming (NC) or not applicable, with comments. The next one is due two weeks later.
  - Service and refill: every six months the extinguishers are serviced and refilled; the site sends the
    contractor's proof. The next date is filled in six months on, and the SHE team is reminded two weeks
    before it (services.fire_inspections.send_reminders).
The SHE team is told about every submission, and about anything not conforming.
"""
import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session, selectinload, undefer

from database import get_db
from models.fire_inspection import FireInspection, FireInspectionFile
from models.site import Site
from models.user import User
from services.audit_service import log_action
from services.auth_services import OVERSIGHT_ROLES, get_current_user, require_role
from services.clock import local_today
from services.files import clean_filename, file_response, is_viewable, read_upload
from services.fire_inspections import ITEMS, KINDS, RESULTS, checklist, default_next_due, latest
from services.notifications import notify, team, who
from services.richtext import clean_html

router = APIRouter(prefix="/fire-inspections", tags=["Fire equipment inspections"])

SHE_ROLES = ("she_team", "she_officer", "admin", "super_admin")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_FILES = 10


def _can_see_site(user: User, site: Optional[Site]) -> bool:
    if site is None:
        return False
    if user.role in SHE_ROLES or user.role in OVERSIGHT_ROLES:
        return True
    if user.role == "site_manager":
        return user.site_id == site.id
    if user.role == "regional_manager":
        return bool(user.region) and site.region == user.region
    return False


def _may_submit(user: User, site: Site) -> bool:
    return user.role in SHE_ROLES or (user.role == "site_manager" and user.site_id == site.id)


def _load(db: Session, user: User, inspection_id: int) -> tuple:
    insp = db.query(FireInspection).filter(FireInspection.id == inspection_id).first()
    site = db.query(Site).filter(Site.id == insp.site_id).first() if insp else None
    if not insp or not _can_see_site(user, site):
        raise HTTPException(status_code=404, detail="Inspection not found")
    return insp, site


def _iso(v):
    return v.isoformat() if v else None


def _file_out(f: FireInspectionFile) -> dict:
    return {"id": f.id, "filename": f.filename, "content_type": f.content_type, "size": f.size,
            "is_image": f.content_type in IMAGE_TYPES, "viewable": is_viewable(f.filename)}


def _not_conforming(insp: FireInspection) -> list:
    return [k for k, a in (insp.answers or {}).items() if (a or {}).get("result") == "NC"]


def _out(insp: FireInspection, site: Site, names: dict, full: bool = False) -> dict:
    out = {
        "id": insp.id, "kind": insp.kind, "kind_label": KINDS.get(insp.kind, insp.kind),
        "site_id": insp.site_id, "site_name": site.name if site else None, "region": site.region if site else None,
        "inspection_date": _iso(insp.inspection_date), "inspector_name": insp.inspector_name,
        "contractor": insp.contractor, "extinguishers": insp.extinguishers, "next_due": _iso(insp.next_due),
        "not_conforming": len(_not_conforming(insp)), "file_count": len(insp.files),
        "submitted_by_name": names.get(insp.created_by), "created_at": _iso(insp.created_at),
    }
    if full:
        out.update({
            "comments": insp.comments,
            "answers": insp.answers or {},
            "files": [_file_out(f) for f in insp.files],
        })
    return out


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i} or {0}
    return {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_(ids))}


def _due(insp: Optional[FireInspection], today: date) -> Optional[dict]:
    if not insp:
        return None
    return {"id": insp.id, "last": _iso(insp.inspection_date), "next_due": _iso(insp.next_due),
            "days_left": (insp.next_due - today).days, "overdue": insp.next_due < today}


@router.get("/checklist")
def get_checklist(current_user: User = Depends(get_current_user)):
    return {"kinds": KINDS, "results": list(RESULTS), "sections": checklist()}


@router.get("/")
def list_fire_inspections(
    site_id: Optional[int] = Query(None, gt=0),
    region: Optional[str] = Query(None, max_length=100),
    kind: Optional[str] = Query(None, pattern="^(fortnightly|service_refill)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sites = {s.id: s for s in db.query(Site).all() if _can_see_site(current_user, s)}
    chosen = [s for s in sites.values() if (not site_id or s.id == site_id) and (not region or s.region == region)]
    query = db.query(FireInspection).options(selectinload(FireInspection.files)).filter(
        FireInspection.site_id.in_([s.id for s in chosen] or [0]))
    if kind:
        query = query.filter(FireInspection.kind == kind)
    rows = query.order_by(FireInspection.inspection_date.desc(), FireInspection.id.desc()).all()
    names = _names(db, [r.created_by for r in rows])
    today = local_today()
    schedule = [
        {"site_id": s.id, "site_name": s.name, "region": s.region,
         "fortnightly": _due(latest(db, s.id, "fortnightly"), today),
         "service_refill": _due(latest(db, s.id, "service_refill"), today)}
        for s in sorted(chosen, key=lambda s: (s.name or "").lower())
    ]
    return {
        "regions": sorted({s.region for s in sites.values() if s.region}),
        "schedule": schedule,
        "inspections": [_out(r, sites.get(r.site_id), names) for r in rows],
    }


@router.get("/{inspection_id}")
def get_fire_inspection(inspection_id: int, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    insp, site = _load(db, current_user, inspection_id)
    return _out(insp, site, _names(db, [insp.created_by]), full=True)


def _clean_answers(kind: str, raw: Optional[str]) -> dict:
    if kind != "fortnightly":
        return {}
    try:
        given = json.loads(raw or "{}")
    except ValueError:
        raise HTTPException(status_code=422, detail="The checklist answers couldn't be read.")
    if not isinstance(given, dict):
        raise HTTPException(status_code=422, detail="The checklist answers couldn't be read.")
    answers, missing = {}, []
    for key, text in ITEMS.items():
        a = given.get(key) or {}
        result = a.get("result") if isinstance(a, dict) else None
        if result not in RESULTS:
            missing.append(text)
            continue
        comment = " ".join(str(a.get("comment") or "").split())[:500] or None
        answers[key] = {"result": result, "comment": comment}
    if missing:
        raise HTTPException(status_code=422, detail=(
            f"Answer every item on the checklist ({len(missing)} still to answer, starting with \"{missing[0]}\")."))
    return answers


async def _store(db: Session, insp: FireInspection, uploads: List[UploadFile], user: User) -> None:
    if len(insp.files) + len(uploads) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"An inspection can have at most {MAX_FILES} files.")
    for upload in uploads:
        filename, content_type = clean_filename(upload)
        data = await read_upload(upload)
        insp.files.append(FireInspectionFile(filename=filename, content_type=content_type, size=len(data),
                                             data=data, uploaded_by=user.id))


@router.post("/", status_code=201)
async def submit_fire_inspection(
    request: Request,
    kind: str = Form(..., pattern="^(fortnightly|service_refill)$"),
    inspection_date: date = Form(...),
    inspector_name: str = Form(..., min_length=2, max_length=150),
    site_id: Optional[int] = Form(None, gt=0),
    answers: Optional[str] = Form(None, max_length=50000),
    comments: Optional[str] = Form(None, max_length=20000, description="formatted text: bold, italic, underline, lists"),
    contractor: Optional[str] = Form(None, max_length=200),
    extinguishers: Optional[int] = Form(None, ge=0, le=10000),
    next_due: Optional[date] = Form(None),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*SHE_ROLES, "site_manager")),
):
    site_id = current_user.site_id if current_user.role == "site_manager" else site_id
    site = db.query(Site).filter(Site.id == site_id).first() if site_id else None
    if not site:
        raise HTTPException(status_code=422 if not site_id else 404,
                            detail="Choose the site that was inspected." if not site_id else "Site not found")
    if not _may_submit(current_user, site):
        raise HTTPException(status_code=403, detail="You can only send inspections for your own site.")
    if inspection_date > local_today():
        raise HTTPException(status_code=422, detail="The inspection date can't be in the future.")
    files = [f for f in files if f and f.filename]
    if kind == "service_refill" and not files:
        raise HTTPException(status_code=422, detail=(
            "Attach proof of the service and refill (the service certificate, job card or photos of the tags)."))
    if next_due is not None and next_due <= inspection_date:
        raise HTTPException(status_code=422, detail="The next date must come after the inspection date.")

    insp = FireInspection(
        kind=kind, site_id=site.id, inspection_date=inspection_date,
        inspector_name=" ".join(inspector_name.split()),
        contractor=(" ".join(contractor.split()) or None) if contractor and kind == "service_refill" else None,
        extinguishers=extinguishers if kind == "service_refill" else None,
        answers=_clean_answers(kind, answers),
        comments=clean_html(comments),
        next_due=next_due or default_next_due(kind, inspection_date),
        created_by=current_user.id,
    )
    db.add(insp)
    await _store(db, insp, files, current_user)
    db.commit()
    db.refresh(insp)

    label = KINDS[kind]
    nc = len(_not_conforming(insp))
    title = f"{site.name}: {label.lower()} sent"
    if nc:
        title = f"{site.name}: {nc} item{'s' if nc != 1 else ''} not conforming on the fire equipment inspection"
    message = f"{who(current_user)} sent it for {inspection_date.strftime('%d %B %Y').lstrip('0')}. Next due {insp.next_due.strftime('%d %B %Y').lstrip('0')}."
    notify(db, team(db), kind="fire_inspection", title=title, message=message,
           link=f"/inspections?tab=fire&open={insp.id}", resource="fire_inspections", resource_id=insp.id,
           actor=current_user)
    log_action(db=db, user=current_user, action="CREATE_FIRE_INSPECTION", resource="fire_inspections",
               resource_id=insp.id, details=f"{label} for {site.name} ({inspection_date.isoformat()})",
               ip_address=request.client.host if request.client else None)
    return _out(insp, site, _names(db, [insp.created_by]), full=True)


@router.post("/{inspection_id}/files", status_code=201)
async def add_fire_inspection_file(
    inspection_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*SHE_ROLES, "site_manager")),
):
    insp, site = _load(db, current_user, inspection_id)
    if not _may_submit(current_user, site):
        raise HTTPException(status_code=403, detail="You can only add files to your own site's inspections.")
    await _store(db, insp, [file], current_user)
    db.commit()
    db.refresh(insp)
    return _out(insp, site, _names(db, [insp.created_by]), full=True)


@router.get("/files/{file_id}")
def get_fire_inspection_file(file_id: int, download: bool = Query(False), db: Session = Depends(get_db),
                             current_user: User = Depends(get_current_user)):
    f = (db.query(FireInspectionFile).options(undefer(FireInspectionFile.data))
         .filter(FireInspectionFile.id == file_id).first())
    if not f:
        raise HTTPException(status_code=404, detail="File not found")
    _load(db, current_user, f.inspection_id)
    kind = "inline" if is_viewable(f.filename) and not download else "attachment"
    return file_response(f.data, f.content_type, f.filename, kind)
