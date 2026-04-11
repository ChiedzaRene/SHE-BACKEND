from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.incident import Incident
from models.user import User
from schemas.incident import IncidentCreate, IncidentUpdate, IncidentResponse
from services.auth_services import get_current_user, require_role
from typing import List

router = APIRouter(prefix="/incidents", tags=["Incidents"])

# Get all incidents - SHE Team and Admin only
@router.get("/", response_model=List[IncidentResponse])
def get_all_incidents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return db.query(Incident).filter(Incident.site_id == current_user.site_id).all()
    return db.query(Incident).all()

# Global metrics - MUST be before /metrics/{site_id}
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

    total_incidents = len(incidents)
    lost_time_injuries = sum(1 for i in incidents if i.lost_time_days > 0)
    total_hours = sum(i.total_hours_worked for i in incidents if i.total_hours_worked)
    trir = round((total_incidents * 200000) / total_hours, 2) if total_hours > 0 else 0
    ltifr = round((lost_time_injuries * 1000000) / total_hours, 2) if total_hours > 0 else 0
    return {
        "scope": scope,
        "total_incidents": total_incidents,
        "lost_time_injuries": lost_time_injuries,
        "total_hours_worked": total_hours,
        "trir": trir,
        "ltifr": ltifr
    }

# Site metrics - AFTER global
@router.get("/metrics/{site_id}")
def get_site_metrics(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    incidents = db.query(Incident).filter(Incident.site_id == site_id).all()
    total_incidents = len(incidents)
    lost_time_injuries = sum(1 for i in incidents if i.lost_time_days > 0)
    total_hours = sum(i.total_hours_worked for i in incidents if i.total_hours_worked)
    trir = round((total_incidents * 200000) / total_hours, 2) if total_hours > 0 else 0
    ltifr = round((lost_time_injuries * 1000000) / total_hours, 2) if total_hours > 0 else 0
    return {
        "site_id": site_id,
        "total_incidents": total_incidents,
        "lost_time_injuries": lost_time_injuries,
        "total_hours_worked": total_hours,
        "trir": trir,
        "ltifr": ltifr
    }

# Get incidents by site
@router.get("/site/{site_id}", response_model=List[IncidentResponse])
def get_site_incidents(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    incidents = db.query(Incident).filter(Incident.site_id == site_id).all()
    return incidents

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
    return new_incident

# Update incident
@router.put("/{incident_id}", response_model=IncidentResponse)
def update_incident(
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
    return incident