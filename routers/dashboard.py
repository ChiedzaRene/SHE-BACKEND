from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models.site import Site
from models.user import User
from services.access import assert_site_access
from services.auth_services import get_current_user
from services.clock import local_today
from services.dashboard import PERIODS, period_range, summarise

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
def dashboard_summary(
    period: str = Query("quarter", description="month, last_month, quarter, last_quarter, 3m, 6m, ytd or 12m"),
    site_id: Optional[int] = Query(None, gt=0),
    region: Optional[str] = Query(None, max_length=100, description="only the sites in this region"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Everything the dashboard shows for a period and one site (or all), plus the previous period to compare."""
    if period not in PERIODS:
        raise HTTPException(status_code=422, detail=f"period must be one of: {', '.join(PERIODS)}")
    if current_user.role == "site_manager":
        site_id = current_user.site_id  # managers only ever see their own site
    if site_id:
        assert_site_access(current_user, site_id)
        if not db.query(Site.id).filter(Site.id == site_id).first():
            raise HTTPException(status_code=404, detail="Site not found")
        site_ids = [site_id]
    else:
        query = db.query(Site.id)
        if region:
            query = query.filter(Site.region == region)
        site_ids = [sid for (sid,) in query.order_by(Site.name).all()]

    today = local_today()
    (start, end), (prev_start, prev_end) = period_range(period, today)
    return {
        "period": period,
        "period_name": PERIODS[period],
        "site_id": site_id,
        "region": None if site_id else region,
        "regions": sorted({r for (r,) in db.query(Site.region).filter(Site.region.isnot(None)).all() if r}),
        "current": summarise(db, site_ids, start, end, today),
        "previous": summarise(db, site_ids, prev_start, prev_end, today),
    }
