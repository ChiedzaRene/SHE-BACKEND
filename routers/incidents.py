from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from database import get_db
from models.incident import Incident
from models.user import User
from schemas.incident import IncidentCreate, IncidentUpdate, IncidentResponse
from services.auth_services import get_current_user, require_role
from services.audit_service import log_action
from typing import List

router = APIRouter(prefix="/incidents", tags=["Incidents"])

STANDARD_HOURS = 200_000

def calculate_metrics(db: Session, site_id=None, scope="site"):
    # Count in the database instead of loading every incident row into Python
    query = db.query(
        func.count(Incident.id),
        func.coalesce(func.sum(case((Incident.lost_time_days > 0, 1), else_=0)), 0),
    )
    if site_id is not None:
        query = query.filter(Incident.site_id == site_id)
    total_incidents, lost_time_injuries = query.one()
    total_incidents, lost_time_injuries = int(total_incidents), int(lost_time_injuries)
    trir  = round((total_incidents    * 200_000) / STANDARD_HOURS, 2)
    ltifr = round((lost_time_injuries * 200_000) / STANDARD_HOURS, 2)
    return {
        "scope": scope,
        "total_incidents": total_incidents,
        "lost_time_injuries": lost_time_injuries,
        "trir": trir,
        "ltifr": ltifr
    }

# Get all incidents
@router.get("/", response_model=List[IncidentResponse])
def get_all_incidents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return db.query(Incident).filter(Incident.site_id == current_user.site_id).all()
    return db.query(Incident).all()

# Global metrics
@router.get("/metrics/global")
def get_global_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return calculate_metrics(db, current_user.site_id, f"site_{current_user.site_id}")
    return calculate_metrics(db, None, "global")

# Site metrics
@router.get("/metrics/{site_id}")
def get_site_metrics(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return calculate_metrics(db, site_id, f"site_{site_id}")

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