from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from database import get_db
from models.site import Site
from models.site_hours import SiteHours
from models.user import User
from schemas.site_hours import SiteHoursResponse, SiteHoursUpsert
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role
from services.notifications import notify, site_name, team, who
from services.safety_metrics import month_start

router = APIRouter(prefix="/site-hours", tags=["Site Hours"])


@router.get("/", response_model=List[SiteHoursResponse])
def list_site_hours(
    site_id: Optional[int] = Query(None),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        site_id = current_user.site_id
    query = db.query(SiteHours)
    if site_id:
        query = query.filter(SiteHours.site_id == site_id)
    if year:
        query = query.filter(SiteHours.period >= date(year, 1, 1), SiteHours.period <= date(year, 12, 1))
    return query.order_by(SiteHours.period.desc(), SiteHours.site_id).all()


@router.put("/", response_model=SiteHoursResponse)
def upsert_site_hours(
    request: Request,
    payload: SiteHoursUpsert,
    db: Session = Depends(get_db),
    # Each site's manager enters their own site's monthly hours and headcount. Admins can correct them.
    # The SHE team only reads them, so the figures behind TRIR/LTIFR come from the site itself.
    current_user: User = Depends(require_role("site_manager", "admin", "super_admin")),
):
    if current_user.role == "site_manager" and payload.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="You can only enter hours for your own site")
    year, month = (int(p) for p in payload.month.split("-"))
    period = date(year, month, 1)
    if period > month_start(date.today()):
        raise HTTPException(status_code=400, detail="Cannot enter hours for a future month")
    if not db.query(Site.id).filter(Site.id == payload.site_id).first():
        raise HTTPException(status_code=404, detail="Site not found")

    row = (
        db.query(SiteHours)
        .filter(SiteHours.site_id == payload.site_id, SiteHours.period == period)
        .first()
    )
    previous = row.hours_worked if row else None
    if row:
        row.hours_worked = payload.hours_worked
        if payload.workers is not None:
            row.workers = payload.workers
        row.entered_by = current_user.id
    else:
        row = SiteHours(
            site_id=payload.site_id,
            period=period,
            hours_worked=payload.hours_worked,
            workers=payload.workers,
            entered_by=current_user.id,
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    log_action(
        db=db,
        user=current_user,
        action="UPSERT_SITE_HOURS",
        resource="site_hours",
        resource_id=row.id,
        details=f"Site #{row.site_id} {payload.month}: {previous} -> {row.hours_worked} hours"
                + (f", {row.workers} workers" if row.workers is not None else ""),
        ip_address=request.client.host if request.client else None,
    )
    where = site_name(db, row.site_id)
    notify(
        db, team(db), kind="hours_entered",
        title=f"Hours worked {'updated' if previous is not None else 'entered'} for {where} ({period:%B %Y})",
        message=f"{who(current_user)}: {row.hours_worked:,.0f} hours"
                + (f", {row.workers} workers" if row.workers is not None else ""),
        link="/site-hours", resource="site_hours", resource_id=row.id, actor=current_user,
    )
    return row
