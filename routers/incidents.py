from fastapi import APIRouter, Depends, HTTPException, Request
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

def calculate_metrics(incidents, scope="site"):
    total_incidents = len(incidents)
    lost_time_injuries = sum(1 for i in incidents if i.lost_time_days and i.lost_time_days > 0)
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
        incidents = db.query(Incident).filter(Incident.site_id == current_user.site_id).all()
        scope = f"site_{current_user.site_id}"
    else:
        incidents = db.query(Incident).all()
        scope = "global"
    return calculate_metrics(incidents, scope)

# Site metrics
@router.get("/metrics/{site_id}")
def get_site_metrics(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incidents = db.query(Incident).filter(Incident.site_id == site_id).all()
    return calculate_metrics(incidents, scope=f"site_{site_id}")

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
    return incident

# Create incident
@router.post("/", response_model=IncidentResponse)
def create_incident(
    request: Request,
    incident_data: IncidentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
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