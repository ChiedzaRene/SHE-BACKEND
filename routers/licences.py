"""Site licences: what each site holds, when each is due, and the certificates.

The SHE team and admins keep the register for every site; a site manager can record their own site's
licences (e.g. after paying a renewal). Recording a licence of a type the site already has counts as the
renewal: the old one is kept in the history and its reminders stop.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session, undefer

from database import get_db
from models.site import Site
from models.site_licence import SiteLicence
from models.user import User
from services.access import assert_site_access
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role
from services.clock import local_today
from services.files import clean_filename, file_response, is_viewable, read_upload
from services.licences import LICENCE_TYPES, send_reminders, status_of

router = APIRouter(prefix="/licences", tags=["Licences"])

EDITORS = ("she_team", "she_officer", "admin", "super_admin", "site_manager")


def _out(lic: SiteLicence, today: date, names: dict) -> dict:
    name, issuer = LICENCE_TYPES.get(lic.licence_type, (lic.licence_type, None))
    return {
        "id": lic.id, "site_id": lic.site_id, "licence_type": lic.licence_type, "name": name, "issuer": issuer,
        "licence_number": lic.licence_number, "issue_date": lic.issue_date.isoformat() if lic.issue_date else None,
        "expiry_date": lic.expiry_date.isoformat(), "days_left": (lic.expiry_date - today).days,
        "status": status_of(lic.expiry_date, today), "amount": lic.amount, "notes": lic.notes,
        "document_name": lic.document_name, "document_viewable": bool(lic.document_name) and is_viewable(lic.document_name),
        "current": lic.superseded_by is None, "recorded_by_name": names.get(lic.created_by),
        "created_at": lic.created_at.isoformat() if lic.created_at else None,
    }


def _visible_sites(db: Session, user: User, site_id: Optional[int], region: Optional[str]) -> list:
    query = db.query(Site)
    if user.role == "site_manager":
        query = query.filter(Site.id == user.site_id)
    elif user.role == "regional_manager":
        query = query.filter(Site.region == user.region)
    if site_id:
        query = query.filter(Site.id == site_id)
    if region:
        query = query.filter(Site.region == region)
    return query.order_by(Site.name).all()


@router.get("/types")
def licence_types():
    return [{"key": k, "name": n, "issuer": i} for k, (n, i) in LICENCE_TYPES.items()]


@router.get("/")
def register(
    site_id: Optional[int] = Query(None, gt=0),
    region: Optional[str] = Query(None, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every site against every licence type: the current licence (or none) and its history."""
    today = local_today()
    send_reminders(db, today)  # nobody waits for the hourly check to see a reminder that is due
    sites = _visible_sites(db, current_user, site_id, region)
    ids = [s.id for s in sites] or [0]
    rows = db.query(SiteLicence).filter(SiteLicence.site_id.in_(ids)).order_by(SiteLicence.expiry_date.desc()).all()
    names = {u.id: (u.full_name or u.email) for u in db.query(User).filter(User.id.in_({r.created_by for r in rows} or {0}))}
    out_sites = []
    counts = {"valid": 0, "due_3_months": 0, "due_1_month": 0, "expired": 0, "missing": 0}
    for s in sites:
        mine = [r for r in rows if r.site_id == s.id]
        cells = []
        for key, (name, issuer) in LICENCE_TYPES.items():
            history = [r for r in mine if r.licence_type == key]
            current = next((r for r in history if r.superseded_by is None), None)
            cell = {
                "licence_type": key, "name": name, "issuer": issuer,
                "current": _out(current, today, names) if current else None,
                "status": status_of(current.expiry_date, today) if current else "missing",
                "history": [_out(r, today, names) for r in history if r is not current],
            }
            counts[cell["status"]] += 1
            cells.append(cell)
        out_sites.append({"site_id": s.id, "name": s.name, "region": s.region, "licences": cells})
    upcoming = sorted(
        (c["current"] | {"site_name": s["name"]} for s in out_sites for c in s["licences"]
         if c["current"] and c["status"] in ("due_3_months", "due_1_month", "expired")),
        key=lambda x: x["expiry_date"],
    )
    all_regions = sorted({r for (r,) in db.query(Site.region).filter(Site.region.isnot(None)).all() if r})
    return {
        "types": licence_types(), "regions": all_regions, "counts": counts, "sites": out_sites, "due": upcoming,
        "can_edit": current_user.role in EDITORS,
    }


@router.post("/", status_code=201)
async def record_licence(
    request: Request,
    site_id: int = Form(..., gt=0),
    licence_type: str = Form(...),
    expiry_date: date = Form(...),
    issue_date: Optional[date] = Form(None),
    licence_number: Optional[str] = Form(None, max_length=100),
    amount: Optional[float] = Form(None, ge=0, le=100_000_000),
    notes: Optional[str] = Form(None, max_length=2000),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*EDITORS)),
):
    """Record a licence (or its renewal) for a site, with the certificate if there is one."""
    assert_site_access(current_user, site_id)
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    if licence_type not in LICENCE_TYPES:
        raise HTTPException(status_code=422, detail="Choose one of the licence types.")
    if issue_date and issue_date > expiry_date:
        raise HTTPException(status_code=422, detail="The issue date must be before the expiry date.")
    lic = SiteLicence(site_id=site.id, licence_type=licence_type, expiry_date=expiry_date, issue_date=issue_date,
                      licence_number=(licence_number or "").strip() or None, amount=amount,
                      notes=(notes or "").strip() or None, created_by=current_user.id)
    if file is not None and file.filename:
        lic.document_name, lic.document_type = clean_filename(file)
        lic.document = await read_upload(file)
        lic.document_size = len(lic.document)
    db.add(lic)
    db.flush()
    previous = (db.query(SiteLicence).filter(SiteLicence.site_id == site.id, SiteLicence.licence_type == licence_type,
                                             SiteLicence.superseded_by.is_(None), SiteLicence.id != lic.id).all())
    for old in previous:
        old.superseded_by = lic.id
    db.commit()
    db.refresh(lic)
    name = LICENCE_TYPES[licence_type][0]
    log_action(db=db, user=current_user, action="RECORD_LICENCE", resource="licences", resource_id=lic.id,
               details=f"{'Renewed' if previous else 'Recorded'} {name} for {site.name}, due {expiry_date.isoformat()}",
               ip_address=request.client.host if request.client else None)
    send_reminders(db)  # a licence entered close to its due date gets its reminder straight away
    return _out(lic, local_today(), {current_user.id: current_user.full_name or current_user.email})


@router.put("/{licence_id}")
def correct_licence(
    request: Request,
    licence_id: int,
    expiry_date: Optional[date] = Form(None),
    issue_date: Optional[date] = Form(None),
    licence_number: Optional[str] = Form(None, max_length=100),
    amount: Optional[float] = Form(None, ge=0, le=100_000_000),
    notes: Optional[str] = Form(None, max_length=2000),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*EDITORS)),
):
    """Correct a licence's details (a new expiry date restarts its reminders)."""
    lic = db.query(SiteLicence).filter(SiteLicence.id == licence_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="Licence not found")
    assert_site_access(current_user, lic.site_id)
    if expiry_date and expiry_date != lic.expiry_date:
        lic.expiry_date = expiry_date
        lic.reminded_90 = lic.reminded_30 = lic.reminded_expired = None
    if issue_date is not None:
        lic.issue_date = issue_date
    if licence_number is not None:
        lic.licence_number = licence_number.strip() or None
    if amount is not None:
        lic.amount = amount
    if notes is not None:
        lic.notes = notes.strip() or None
    lic.updated_at = datetime.now(timezone.utc)
    db.commit()
    log_action(db=db, user=current_user, action="UPDATE_LICENCE", resource="licences", resource_id=lic.id,
               details=f"Corrected licence #{lic.id}", ip_address=request.client.host if request.client else None)
    send_reminders(db)
    return _out(lic, local_today(), {})


@router.delete("/{licence_id}")
def delete_licence(request: Request, licence_id: int, db: Session = Depends(get_db),
                   current_user: User = Depends(require_role("she_team", "she_officer", "admin", "super_admin"))):
    lic = db.query(SiteLicence).filter(SiteLicence.id == licence_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="Licence not found")
    # an earlier licence this one replaced becomes the current one again
    db.query(SiteLicence).filter(SiteLicence.superseded_by == lic.id).update({SiteLicence.superseded_by: None})
    db.delete(lic)
    db.commit()
    log_action(db=db, user=current_user, action="DELETE_LICENCE", resource="licences", resource_id=licence_id,
               details=f"Deleted licence #{licence_id}", ip_address=request.client.host if request.client else None)
    return {"message": "Licence deleted"}


@router.get("/{licence_id}/document")
def licence_document(licence_id: int, download: bool = Query(False), db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    lic = db.query(SiteLicence).options(undefer(SiteLicence.document)).filter(SiteLicence.id == licence_id).first()
    if not lic or not lic.document_name:
        raise HTTPException(status_code=404, detail="No certificate for this licence")
    assert_site_access(current_user, lic.site_id)
    if current_user.role == "regional_manager":
        site = db.query(Site).filter(Site.id == lic.site_id).first()
        if not site or site.region != current_user.region:
            raise HTTPException(status_code=404, detail="No certificate for this licence")
    kind = "inline" if is_viewable(lic.document_name) and not download else "attachment"
    return file_response(lic.document, lic.document_type, lic.document_name, kind)
