"""Inspection reports and their non-conformities (NCs), from the SHE team's visit to the NC being closed.

  1. The SHE team writes the report (draft): heading sections, conformities, and each NC with photos.
  2. Submitting it sends the NCs to the regional office for the site's region (and the site sees the report).
  3. The regional office acknowledges each NC: the corrective action it recommends, who will do it and by
     when. That opens a corrective action for the NC.
  4. The person responsible marks it completed and says how it was closed.
  5. The SHE team reviews it: closed (verified), or open again. The reviewer and date are kept.
  The report is closed when every NC in it is closed. NCs still open from a site's earlier reports are
  shown in its later reports as previous NCs.
"""
import re
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, undefer

from database import get_db
from models.corrective_action import CorrectiveAction
from models.site import Site
from models.site_inspection import InspectionNC, InspectionPhoto, SiteInspection
from models.user import User
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role
from services.clock import local_today
from services.files import clean_filename, file_response, read_upload
from services.notifications import notify, short, site_managers, team, who
from services.richtext import clean_html, plain_text

router = APIRouter(prefix="/site-inspections", tags=["Inspections"])

SHE_ROLES = ("she_team", "admin", "super_admin")
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_PHOTOS = 10
SECTIONS = ("introduction", "criteria", "objectives", "findings_summary", "conformities")


# ---------------- who may see and do what ----------------

def _is_she(user: User) -> bool:
    return user.role in SHE_ROLES


def _is_admin(user: User) -> bool:
    return user.role in ("admin", "super_admin")


def _regional_for(user: User, site: Optional[Site]) -> bool:
    return user.role == "regional_manager" and bool(user.region) and site is not None and site.region == user.region


def _can_see(user: User, insp: SiteInspection, site: Optional[Site]) -> bool:
    if _is_she(user):
        return True
    if insp.status == "draft":
        return False
    if user.role == "site_manager":
        return user.site_id == insp.site_id
    return _regional_for(user, site)


def _load(db: Session, user: User, inspection_id: int) -> tuple:
    insp = db.query(SiteInspection).filter(SiteInspection.id == inspection_id).first()
    site = db.query(Site).filter(Site.id == insp.site_id).first() if insp else None
    if not insp or not _can_see(user, insp, site):
        raise HTTPException(status_code=404, detail="Inspection not found")
    return insp, site


def _load_nc(db: Session, user: User, nc_id: int):
    nc = db.query(InspectionNC).filter(InspectionNC.id == nc_id).first()
    if not nc:
        raise HTTPException(status_code=404, detail="Non-conformity not found")
    insp, site = _load(db, user, nc.inspection_id)
    return nc, insp, site


def _draft_only(insp: SiteInspection):
    if insp.status != "draft":
        raise HTTPException(status_code=409, detail="This report has been submitted and can no longer be changed.")


# ---------------- output ----------------

def _site_code(site: Site) -> str:
    if site.code:
        return site.code
    words = re.findall(r"[A-Za-z0-9]+", site.name or "")
    if len(words) >= 2:
        return "".join(w[0] for w in words[:3]).upper()
    return (words[0][:3] if words else "SITE").upper()


def _names(db: Session, ids) -> dict:
    ids = {i for i in ids if i} or {0}
    return {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_(ids))}


def _iso(v):
    return v.isoformat() if v else None


def _overdue(nc: InspectionNC, today: date) -> bool:
    return bool(nc.due_date and nc.status in ("raised", "assigned") and nc.due_date < today)


def _nc_out(nc: InspectionNC, names: dict, user: User, insp: SiteInspection, site: Site, today: date) -> dict:
    return {
        "id": nc.id, "inspection_id": nc.inspection_id, "seq": nc.seq, "serial": nc.serial, "title": nc.title,
        "details": nc.details, "reference": nc.reference, "status": nc.status,
        "recommendation": nc.recommendation, "assigned_to": nc.assigned_to,
        "assigned_to_name": names.get(nc.assigned_to), "due_date": _iso(nc.due_date),
        "overdue": _overdue(nc, today),
        "acknowledged_by_name": names.get(nc.acknowledged_by), "acknowledged_at": _iso(nc.acknowledged_at),
        "corrective_action_id": nc.corrective_action_id,
        "completion_notes": nc.completion_notes, "completed_by_name": names.get(nc.completed_by),
        "completed_at": _iso(nc.completed_at),
        "reviewed_by_name": nc.reviewed_by_name, "reviewed_at": _iso(nc.reviewed_at),
        "review_outcome": nc.review_outcome, "review_comment": nc.review_comment,
        "photos": [{"id": p.id, "kind": p.kind, "filename": p.filename} for p in nc.photos],
        "can": {
            "edit": _is_she(user) and insp.status == "draft",
            "acknowledge": nc.status in ("raised", "assigned") and (_regional_for(user, site) or _is_admin(user)),
            "complete": nc.status == "assigned" and _may_complete(user, nc, site),
            "review": nc.status == "completed" and _is_she(user),
        },
    }


def _may_complete(user: User, nc: InspectionNC, site: Site) -> bool:
    return (nc.assigned_to == user.id or (user.role == "site_manager" and user.site_id == site.id)
            or _regional_for(user, site) or _is_admin(user))


def _counts(ncs) -> dict:
    out = {"total": 0, "raised": 0, "assigned": 0, "completed": 0, "closed": 0, "draft": 0, "overdue": 0}
    today = local_today()
    for nc in ncs:
        out["total"] += 1
        out[nc.status] = out.get(nc.status, 0) + 1
        out["overdue"] += _overdue(nc, today)
    return out


def _summary(insp: SiteInspection, site: Site, names: dict) -> dict:
    return {
        "id": insp.id, "number": insp.number, "site_id": insp.site_id, "site_name": site.name if site else None,
        "site_code": _site_code(site) if site else None, "region": site.region if site else None,
        "inspection_date": _iso(insp.inspection_date), "inspectors": insp.inspectors, "status": insp.status,
        "created_by_name": names.get(insp.created_by), "submitted_at": _iso(insp.submitted_at),
        "closed_at": _iso(insp.closed_at), "nc_counts": _counts(insp.ncs),
    }


def _full(db: Session, insp: SiteInspection, site: Site, user: User) -> dict:
    today = local_today()
    previous = (
        db.query(InspectionNC).join(SiteInspection)
        .filter(SiteInspection.site_id == insp.site_id, SiteInspection.number < insp.number,
                SiteInspection.status != "draft", InspectionNC.status != "closed", InspectionNC.status != "draft")
        .order_by(SiteInspection.number, InspectionNC.seq).all()
    ) if insp.status != "closed" else []
    all_ncs = list(insp.ncs) + previous
    names = _names(db, [insp.created_by, insp.submitted_by] + [
        uid for nc in all_ncs for uid in (nc.assigned_to, nc.acknowledged_by, nc.completed_by)])
    prev_inspections = {i.id: i for i in db.query(SiteInspection).filter(
        SiteInspection.id.in_({nc.inspection_id for nc in previous} or {0}))}
    out = _summary(insp, site, names)
    out.update({s: getattr(insp, s) for s in SECTIONS})
    out.update({
        "submitted_by_name": names.get(insp.submitted_by),
        "ncs": [_nc_out(nc, names, user, insp, site, today) for nc in insp.ncs],
        "previous_ncs": [
            {**_nc_out(nc, names, user, prev_inspections[nc.inspection_id], site, today),
             "from_report": prev_inspections[nc.inspection_id].number}
            for nc in previous
        ],
        "can": {
            "edit": _is_she(user) and insp.status == "draft",
            "submit": _is_she(user) and insp.status == "draft",
            "delete": _is_she(user) and insp.status == "draft",
        },
    })
    return out


# ---------------- reading ----------------

@router.get("/")
def list_inspections(
    site_id: Optional[int] = Query(None, gt=0),
    region: Optional[str] = Query(None, max_length=100),
    status: Optional[str] = Query(None, pattern="^(draft|submitted|closed)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sites = {s.id: s for s in db.query(Site).all()}
    query = db.query(SiteInspection)
    if site_id:
        query = query.filter(SiteInspection.site_id == site_id)
    if region:
        query = query.filter(SiteInspection.site_id.in_([s.id for s in sites.values() if s.region == region] or [0]))
    if status:
        query = query.filter(SiteInspection.status == status)
    rows = [i for i in query.order_by(SiteInspection.number.desc()).all() if _can_see(current_user, i, sites.get(i.site_id))]
    names = _names(db, [i.created_by for i in rows])
    return {
        "regions": sorted({s.region for s in sites.values() if s.region}),
        "inspections": [_summary(i, sites.get(i.site_id), names) for i in rows],
    }


@router.get("/my-ncs")
def my_ncs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """NCs waiting on the signed-in person: to acknowledge (regional office), to complete, or to review."""
    sites = {s.id: s for s in db.query(Site).all()}
    rows = (db.query(InspectionNC, SiteInspection).join(SiteInspection)
            .filter(InspectionNC.status.in_(("raised", "assigned", "completed"))).all())
    today = local_today()
    out = []
    for nc, insp in rows:
        site = sites.get(insp.site_id)
        if not _can_see(current_user, insp, site):
            continue
        waiting = (
            (nc.status == "raised" and (_regional_for(current_user, site) or _is_admin(current_user)))
            or (nc.status == "assigned" and (nc.assigned_to == current_user.id
                                             or (current_user.role == "site_manager" and current_user.site_id == site.id)))
            or (nc.status == "completed" and _is_she(current_user))
        )
        if waiting:
            out.append({"id": nc.id, "serial": nc.serial, "title": nc.title, "status": nc.status,
                        "due_date": _iso(nc.due_date), "overdue": _overdue(nc, today), "inspection_id": insp.id,
                        "number": insp.number, "site_name": site.name if site else None})
    return sorted(out, key=lambda r: (not r["overdue"], r["due_date"] or "9999", r["serial"]))


@router.get("/{inspection_id}")
def get_inspection(inspection_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    insp, site = _load(db, current_user, inspection_id)
    return _full(db, insp, site, current_user)


@router.get("/{inspection_id}/assignees")
def assignees(inspection_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Who an NC can be given to: the site's managers, the region's regional managers and the SHE team."""
    insp, site = _load(db, current_user, inspection_id)
    people = db.query(User).filter(User.is_active.is_(True)).all()
    out = []
    for u in people:
        if u.role == "site_manager" and u.site_id == site.id:
            label = "Site manager"
        elif u.role == "regional_manager" and site.region and u.region == site.region:
            label = "Regional office"
        elif u.role == "she_team":
            label = "SHE office"
        else:
            continue
        out.append({"id": u.id, "name": u.full_name or u.email, "role": u.role, "label": label})
    order = {"Site manager": 0, "Regional office": 1, "SHE office": 2}
    return sorted(out, key=lambda r: (order[r["label"]], r["name"].lower()))


# ---------------- writing the report (SHE team) ----------------

class InspectionIn(BaseModel):
    site_id: int = Field(..., gt=0)
    inspection_date: date
    inspectors: Optional[str] = Field(default=None, max_length=300)
    introduction: Optional[str] = Field(default=None, max_length=40000)
    criteria: Optional[str] = Field(default=None, max_length=40000)
    objectives: Optional[str] = Field(default=None, max_length=40000)
    findings_summary: Optional[str] = Field(default=None, max_length=40000)
    conformities: Optional[str] = Field(default=None, max_length=40000)


class InspectionUpdate(BaseModel):
    inspection_date: Optional[date] = None
    inspectors: Optional[str] = Field(default=None, max_length=300)
    introduction: Optional[str] = Field(default=None, max_length=40000)
    criteria: Optional[str] = Field(default=None, max_length=40000)
    objectives: Optional[str] = Field(default=None, max_length=40000)
    findings_summary: Optional[str] = Field(default=None, max_length=40000)
    conformities: Optional[str] = Field(default=None, max_length=40000)


def _apply_sections(insp: SiteInspection, data: dict) -> None:
    for key in SECTIONS:
        if key in data:
            setattr(insp, key, clean_html(data[key]))
    if "inspectors" in data:
        insp.inspectors = " ".join((data["inspectors"] or "").split()) or None
    if data.get("inspection_date"):
        if data["inspection_date"] > local_today():
            raise HTTPException(status_code=422, detail="The inspection date can't be in the future.")
        insp.inspection_date = data["inspection_date"]


@router.post("/", status_code=201)
def create_inspection(
    request: Request, body: InspectionIn, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*SHE_ROLES)),
):
    site = db.query(Site).filter(Site.id == body.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    number = (db.query(func.max(SiteInspection.number)).scalar() or 0) + 1
    insp = SiteInspection(number=number, site_id=site.id, inspection_date=body.inspection_date,
                          status="draft", created_by=current_user.id)
    _apply_sections(insp, body.model_dump())
    db.add(insp)
    db.commit()
    db.refresh(insp)
    log_action(db=db, user=current_user, action="CREATE_SITE_INSPECTION", resource="site_inspections",
               resource_id=insp.id, details=f"Started inspection report No. {number} for {site.name}",
               ip_address=request.client.host if request.client else None)
    return _full(db, insp, site, current_user)


@router.put("/{inspection_id}")
def update_inspection(
    inspection_id: int, body: InspectionUpdate, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*SHE_ROLES)),
):
    insp, site = _load(db, current_user, inspection_id)
    _draft_only(insp)
    _apply_sections(insp, body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(insp)
    return _full(db, insp, site, current_user)


@router.delete("/{inspection_id}")
def delete_draft(
    request: Request, inspection_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*SHE_ROLES)),
):
    insp, site = _load(db, current_user, inspection_id)
    _draft_only(insp)
    number = insp.number
    db.delete(insp)
    db.commit()
    log_action(db=db, user=current_user, action="DELETE_SITE_INSPECTION", resource="site_inspections",
               resource_id=inspection_id, details=f"Deleted draft inspection report No. {number} ({site.name})",
               ip_address=request.client.host if request.client else None)
    return {"message": "Draft deleted"}


class NCIn(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    details: Optional[str] = Field(default=None, max_length=40000)
    reference: Optional[str] = Field(default=None, max_length=500)


def _renumber(db: Session, insp: SiteInspection, site: Site) -> None:
    """Keep the NC serials in order (01, 02, ...) while the report is a draft."""
    ncs = sorted(insp.ncs, key=lambda n: (n.seq, n.id))
    for nc in ncs:
        nc.serial = f"tmp-{nc.id}"
    db.flush()
    code = _site_code(site)
    for i, nc in enumerate(ncs, start=1):
        nc.seq = i
        nc.serial = f"{insp.number}/{code}/{i:02d}"


@router.post("/{inspection_id}/ncs", status_code=201)
def add_nc(inspection_id: int, body: NCIn, db: Session = Depends(get_db),
           current_user: User = Depends(require_role(*SHE_ROLES))):
    insp, site = _load(db, current_user, inspection_id)
    _draft_only(insp)
    seq = max([n.seq for n in insp.ncs] or [0]) + 1
    nc = InspectionNC(inspection_id=insp.id, seq=seq, serial=f"tmp-new-{insp.id}-{seq}",
                      title=" ".join(body.title.split()), details=clean_html(body.details),
                      reference=(body.reference or "").strip() or None, status="draft")
    db.add(nc)
    db.flush()
    db.refresh(insp)
    _renumber(db, insp, site)
    db.commit()
    db.refresh(insp)
    return _full(db, insp, site, current_user)


@router.put("/ncs/{nc_id}")
def update_nc(nc_id: int, body: NCIn, db: Session = Depends(get_db),
              current_user: User = Depends(require_role(*SHE_ROLES))):
    nc, insp, site = _load_nc(db, current_user, nc_id)
    _draft_only(insp)
    nc.title = " ".join(body.title.split())
    nc.details = clean_html(body.details)
    nc.reference = (body.reference or "").strip() or None
    db.commit()
    db.refresh(insp)
    return _full(db, insp, site, current_user)


@router.delete("/ncs/{nc_id}")
def delete_nc(nc_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*SHE_ROLES))):
    nc, insp, site = _load_nc(db, current_user, nc_id)
    _draft_only(insp)
    insp.ncs.remove(nc)
    db.flush()
    _renumber(db, insp, site)
    db.commit()
    db.refresh(insp)
    return _full(db, insp, site, current_user)


@router.post("/ncs/{nc_id}/photos", status_code=201)
async def add_photo(nc_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                    current_user: User = Depends(require_role(*SHE_ROLES))):
    nc, insp, site = _load_nc(db, current_user, nc_id)
    _draft_only(insp)
    filename, content_type = clean_filename(file)
    if content_type not in IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Photos must be images (PNG, JPG, GIF or WebP).")
    if len([p for p in nc.photos if p.kind == "finding"]) >= MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=f"An NC can have up to {MAX_PHOTOS} photos.")
    data = await read_upload(file)
    db.add(InspectionPhoto(nc_id=nc.id, kind="finding", filename=filename, content_type=content_type,
                           size=len(data), data=data, uploaded_by=current_user.id))
    db.commit()
    db.refresh(insp)
    return _full(db, insp, site, current_user)


@router.delete("/photos/{photo_id}")
def delete_photo(photo_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_role(*SHE_ROLES))):
    photo = db.query(InspectionPhoto).filter(InspectionPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    nc, insp, site = _load_nc(db, current_user, photo.nc_id)
    _draft_only(insp)
    db.delete(photo)
    db.commit()
    db.refresh(insp)
    return _full(db, insp, site, current_user)


@router.get("/photos/{photo_id}")
def get_photo(photo_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    photo = db.query(InspectionPhoto).options(undefer(InspectionPhoto.data)).filter(InspectionPhoto.id == photo_id).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    _load_nc(db, current_user, photo.nc_id)
    return file_response(photo.data, photo.content_type, photo.filename, "inline")


def _regional_people(db: Session, site: Site) -> list:
    if not site.region:
        return []
    return db.query(User).filter(User.role == "regional_manager", User.region == site.region,
                                 User.is_active.is_(True)).all()


def _admins(db: Session) -> list:
    return db.query(User).filter(User.role.in_(("admin", "super_admin")), User.is_active.is_(True)).all()


@router.post("/{inspection_id}/submit")
def submit_inspection(request: Request, inspection_id: int, db: Session = Depends(get_db),
                      current_user: User = Depends(require_role(*SHE_ROLES))):
    insp, site = _load(db, current_user, inspection_id)
    _draft_only(insp)
    if not plain_text(insp.introduction) or not plain_text(insp.findings_summary):
        raise HTTPException(status_code=422, detail="Write the introduction and the summary of findings before submitting.")
    now = datetime.now(timezone.utc)
    insp.submitted_by, insp.submitted_at = current_user.id, now
    for nc in insp.ncs:
        nc.status = "raised"
    insp.status = "submitted" if insp.ncs else "closed"
    if not insp.ncs:
        insp.closed_at = now
    db.commit()
    db.refresh(insp)
    count = len(insp.ncs)
    log_action(db=db, user=current_user, action="SUBMIT_SITE_INSPECTION", resource="site_inspections",
               resource_id=insp.id, details=f"Submitted inspection report No. {insp.number} for {site.name} with {count} NC(s)",
               ip_address=request.client.host if request.client else None)
    link = f"/inspections/{insp.id}"
    regional = _regional_people(db, site)
    if count:
        notify(db, regional or _admins(db), kind="ncs_raised",
               title=f"{count} NC{'s' if count != 1 else ''} to acknowledge: {site.name} inspection No. {insp.number}",
               message=f"{who(current_user)} submitted the inspection report. Acknowledge each NC, recommend the corrective "
                       "action, choose who will do it and set a deadline.",
               link=link, resource="site_inspections", resource_id=insp.id, actor=current_user)
    notify(db, site_managers(db, site.id), kind="inspection_report",
           title=f"Inspection report No. {insp.number} for {site.name}",
           message=f"{count} non-conformit{'ies' if count != 1 else 'y'} raised. The regional office will assign the corrective actions.",
           link=link, resource="site_inspections", resource_id=insp.id, actor=current_user)
    return _full(db, insp, site, current_user)


# ---------------- the NC workflow ----------------

class AcknowledgeIn(BaseModel):
    recommendation: str = Field(..., min_length=3, max_length=40000)
    assigned_to: int = Field(..., gt=0)
    due_date: date


@router.post("/ncs/{nc_id}/acknowledge")
def acknowledge_nc(request: Request, nc_id: int, body: AcknowledgeIn, db: Session = Depends(get_db),
                   current_user: User = Depends(get_current_user)):
    nc, insp, site = _load_nc(db, current_user, nc_id)
    if not (_regional_for(current_user, site) or _is_admin(current_user)):
        raise HTTPException(status_code=403, detail="Only the regional office for this site (or an admin) acknowledges NCs.")
    if nc.status not in ("raised", "assigned"):
        raise HTTPException(status_code=409, detail="This NC can't be acknowledged now.")
    allowed = {a["id"] for a in assignees(insp.id, db, current_user)}
    if body.assigned_to not in allowed:
        raise HTTPException(status_code=422, detail="Choose the site manager, a regional manager or a SHE officer.")
    if body.due_date < local_today():
        raise HTTPException(status_code=422, detail="The deadline can't be in the past.")
    recommendation = clean_html(body.recommendation)
    if not recommendation:
        raise HTTPException(status_code=422, detail="Write the recommended corrective action.")
    person = db.query(User).filter(User.id == body.assigned_to).first()
    nc.recommendation, nc.assigned_to, nc.due_date = recommendation, person.id, body.due_date
    nc.acknowledged_by, nc.acknowledged_at = current_user.id, datetime.now(timezone.utc)
    nc.status = "assigned"

    # each NC gets its own corrective action
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == nc.corrective_action_id).first() \
        if nc.corrective_action_id else None
    if not action:
        action = CorrectiveAction(site_id=site.id, nc_id=nc.id, status="open", priority="medium")
        db.add(action)
    action.assigned_to = person.full_name or person.email
    action.action_taken = short(f"NC {nc.serial} ({nc.title}): {plain_text(recommendation)}", 1000)
    action.designation = f"Inspection NC {nc.serial}"
    action.due_date = datetime.combine(body.due_date, datetime.min.time())
    db.flush()
    nc.corrective_action_id = action.id
    db.commit()
    db.refresh(insp)
    log_action(db=db, user=current_user, action="ACKNOWLEDGE_NC", resource="site_inspections", resource_id=insp.id,
               details=f"Acknowledged NC {nc.serial}: assigned to {person.full_name or person.email}, due {body.due_date.isoformat()}",
               ip_address=request.client.host if request.client else None)
    link = f"/inspections/{insp.id}"
    notify(db, [person], kind="nc_assigned",
           title=f"NC {nc.serial} assigned to you: {short(nc.title, 100)}",
           message=f"{who(current_user)} asks you to: {short(plain_text(recommendation), 200)} Due {body.due_date:%d %b %Y}.",
           link=link, resource="site_inspections", resource_id=insp.id, actor=current_user)
    notify(db, [m for m in site_managers(db, site.id) if m.id != person.id], kind="nc_assigned",
           title=f"NC {nc.serial} at {site.name} assigned to {person.full_name or person.email}",
           message=f"Due {body.due_date:%d %b %Y}.", link=link, resource="site_inspections", resource_id=insp.id,
           actor=current_user)
    return _full(db, insp, site, current_user)


@router.post("/ncs/{nc_id}/complete")
async def complete_nc(
    request: Request, nc_id: int, notes: str = Form(..., min_length=3, max_length=20000),
    file: Optional[UploadFile] = File(None), db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The person responsible says the action is done, how it was closed, and may attach a photo."""
    nc, insp, site = _load_nc(db, current_user, nc_id)
    if nc.status != "assigned":
        raise HTTPException(status_code=409, detail="This NC isn't waiting for its corrective action.")
    if not _may_complete(current_user, nc, site):
        raise HTTPException(status_code=403, detail="Only the person it is assigned to, the site or the regional office can complete it.")
    text = " ".join(notes.split()) if "\n" not in notes else notes.strip()
    if len(text) < 3:
        raise HTTPException(status_code=422, detail="Say how the corrective action was closed.")
    if file is not None and file.filename:
        filename, content_type = clean_filename(file)
        if content_type not in IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="Evidence must be a photo (PNG, JPG, GIF or WebP).")
        data = await read_upload(file)
        db.add(InspectionPhoto(nc_id=nc.id, kind="evidence", filename=filename, content_type=content_type,
                               size=len(data), data=data, uploaded_by=current_user.id))
    nc.completion_notes, nc.completed_by, nc.completed_at = text, current_user.id, datetime.now(timezone.utc)
    nc.status = "completed"
    db.commit()
    db.refresh(insp)
    log_action(db=db, user=current_user, action="COMPLETE_NC", resource="site_inspections", resource_id=insp.id,
               details=f"Marked the corrective action for NC {nc.serial} completed",
               ip_address=request.client.host if request.client else None)
    reviewers = team(db)
    notify(db, [u for u in reviewers if u.role == "she_team"] or reviewers, kind="nc_completed",
           title=f"NC {nc.serial} completed at {site.name}: please review",
           message=f"{who(current_user)}: {short(text, 200)}",
           link=f"/inspections/{insp.id}", resource="site_inspections", resource_id=insp.id, actor=current_user)
    return _full(db, insp, site, current_user)


class ReviewIn(BaseModel):
    outcome: str = Field(..., pattern="^(closed|open)$")
    comment: Optional[str] = Field(default=None, max_length=5000)


@router.post("/ncs/{nc_id}/review")
def review_nc(request: Request, nc_id: int, body: ReviewIn, db: Session = Depends(get_db),
              current_user: User = Depends(require_role(*SHE_ROLES))):
    nc, insp, site = _load_nc(db, current_user, nc_id)
    if nc.status != "completed":
        raise HTTPException(status_code=409, detail="Only a completed corrective action can be reviewed.")
    comment = (body.comment or "").strip() or None
    if body.outcome == "open" and not comment:
        raise HTTPException(status_code=422, detail="Say what still needs to be done.")
    now = datetime.now(timezone.utc)
    nc.reviewed_by, nc.reviewed_by_name, nc.reviewed_at = current_user.id, current_user.full_name or current_user.email, now
    nc.review_outcome, nc.review_comment = body.outcome, comment
    nc.status = "closed" if body.outcome == "closed" else "assigned"

    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == nc.corrective_action_id).first() \
        if nc.corrective_action_id else None
    if action:
        if body.outcome == "closed":
            action.status, action.date_resolved = "resolved", now.replace(tzinfo=None)
            action.resolved_by, action.is_successful = nc.reviewed_by_name, "yes"
            action.resolution_notes = nc.completion_notes
        else:
            action.status, action.is_successful = "open", "no"

    # the report closes once every NC in it is closed
    if all(n.status == "closed" for n in insp.ncs):
        insp.status, insp.closed_at = "closed", now
    db.commit()
    db.refresh(insp)
    log_action(db=db, user=current_user, action="REVIEW_NC", resource="site_inspections", resource_id=insp.id,
               details=f"Reviewed NC {nc.serial}: {'closed' if body.outcome == 'closed' else 'still open'}"
                       + (f" ({short(comment, 120)})" if comment else ""),
               ip_address=request.client.host if request.client else None)
    people = [db.query(User).filter(User.id == nc.assigned_to).first()] + _regional_people(db, site) + site_managers(db, site.id)
    if body.outcome == "closed":
        notify(db, people, kind="nc_closed", title=f"NC {nc.serial} closed after review",
               message=f"Verified by {nc.reviewed_by_name} on {now:%d %b %Y}.",
               link=f"/inspections/{insp.id}", resource="site_inspections", resource_id=insp.id, actor=current_user)
    else:
        notify(db, people, kind="nc_reopened", title=f"NC {nc.serial} is still open after review",
               message=f"{nc.reviewed_by_name}: {short(comment, 200)}",
               link=f"/inspections/{insp.id}", resource="site_inspections", resource_id=insp.id, actor=current_user)
    return _full(db, insp, site, current_user)
