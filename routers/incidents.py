from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from database import get_db
from models.incident import Incident
from models.site import Site
from models.user import User
from schemas.incident import IncidentCreate, IncidentUpdate, IncidentResponse
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return db.query(Incident).filter(Incident.site_id == current_user.site_id).all()
    return db.query(Incident).all()

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
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    stats = compute_by_site(db, [site_id], period)[site_id]
    return _metrics_response(stats, f"site_{site_id}", period)

# Get incidents by site
@router.get("/site/{site_id}", response_model=List[IncidentResponse])
def get_site_incidents(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
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
    if current_user.role == "site_manager" and incident.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Access denied")
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
    if current_user.role == "site_manager" and incident.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Access denied")
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