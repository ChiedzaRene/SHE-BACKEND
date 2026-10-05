from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models.incident import Incident
from models.site import Site
from models.user import User
from schemas.incident import IncidentCreate, IncidentUpdate, IncidentResponse
from services.access import assert_site_access
from services.pagination import Pagination
from services.auth_services import get_current_user, require_role
from services.audit_service import log_action
from services.safety_metrics import combine, compute_by_site
from typing import List

router = APIRouter(prefix="/incidents", tags=["Incidents"])

PeriodQuery = Query("12m", pattern="^(12m|ytd)$", description="Rolling 12 months or year to date")


def _metrics_response(stats: dict, scope: str, period: str) -> dict:
    return {"scope": scope, "period": period, **stats}


# Get all incidents
@router.get("/", response_model=List[IncidentResponse])
def get_all_incidents(
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    query = db.query(Incident)
    if current_user.role == "site_manager":
        query = query.filter(Incident.site_id == current_user.site_id)
    return page.apply(query, response, Incident.id.desc()).all()

# Totals for the dashboards (how many, how many still open, split by type) without sending every incident
@router.get("/summary")
def get_incident_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    scope = []
    if current_user.role == "site_manager":
        scope.append(Incident.site_id == current_user.site_id)
    by_type = (
        db.query(Incident.type, func.count(Incident.id))
        .filter(*scope)
        .group_by(Incident.type)
        .order_by(func.count(Incident.id).desc())
        .all()
    )
    open_count = db.query(func.count(Incident.id)).filter(*scope, Incident.resolved.isnot(True)).scalar() or 0
    by_site = db.query(Incident.site_id, func.count(Incident.id)).filter(*scope).group_by(Incident.site_id).all()
    return {
        "total": sum(n for _, n in by_type),
        "open": open_count,
        "by_type": [{"name": t or "Other", "value": n} for t, n in by_type],
        # all-time count per site, for the map bubbles
        "by_site": [{"site_id": sid, "value": n} for sid, n in by_site if sid is not None],
    }


# Per-site rates (TRIR / LTIFR) for the dashboards: one query instead of downloading every incident
@router.get("/metrics/by-site")
def get_metrics_by_site(
    period: str = PeriodQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        site_ids = [current_user.site_id]
    else:
        site_ids = [row[0] for row in db.query(Site.id).all()]
    stats = compute_by_site(db, site_ids, period)
    return [{"site_id": sid, "period": period, **s} for sid, s in sorted(stats.items())]


# Global metrics
@router.get("/metrics/global")
def get_global_metrics(
    period: str = PeriodQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        site_ids = [current_user.site_id]
        scope = f"site_{current_user.site_id}"
    else:
        site_ids = [row[0] for row in db.query(Site.id).all()]
        scope = "global"
    stats = combine(compute_by_site(db, site_ids, period).values())
    return _metrics_response(stats, scope, period)


# Site metrics
@router.get("/metrics/{site_id}")
def get_site_metrics(
    site_id: int,
    period: str = PeriodQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)
    stats = compute_by_site(db, [site_id], period)[site_id]
    return _metrics_response(stats, f"site_{site_id}", period)

# Get incidents by site
@router.get("/site/{site_id}", response_model=List[IncidentResponse])
def get_site_incidents(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    assert_site_access(current_user, site_id)
    return db.query(Incident).filter(Incident.site_id == site_id).all()

# Get one incident
@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    assert_site_access(current_user, incident.site_id)
    return incident

# Create incident
@router.post("/", response_model=IncidentResponse)
def create_incident(
    request: Request,
    incident_data: IncidentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and incident_data.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Cannot log incidents for another site")
    new_incident = Incident(
        **incident_data.model_dump(),
        user_id=current_user.id
    )
    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_INCIDENT",
        resource="incidents",
        resource_id=new_incident.id,
        details=f"Type: {new_incident.type}, Severity: {new_incident.severity}",
        ip_address=request.client.host
    )
    return new_incident

# Update incident
@router.put("/{incident_id}", response_model=IncidentResponse)
def update_incident(
    request: Request,
    incident_id: int,
    incident_data: IncidentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    assert_site_access(current_user, incident.site_id)
    for key, value in incident_data.model_dump(exclude_unset=True).items():
        setattr(incident, key, value)
    db.commit()
    db.refresh(incident)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_INCIDENT",
        resource="incidents",
        resource_id=incident.id,
        details=f"Updated incident #{incident.id}",
        ip_address=request.client.host
    )
    return incident