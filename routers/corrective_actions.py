from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from database import get_db
from models.corrective_action import CorrectiveAction
from models.user import User
from schemas.corrective_action import (
    CorrectiveActionCreate,
    CorrectiveActionUpdate,
    CorrectiveActionResolve,
    CorrectiveActionResponse,
)
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/corrective-actions", tags=["Corrective Actions"])


def _to_response(action: CorrectiveAction) -> dict:
    return {
        "id": action.id,
        "incident_id": action.incident_id,
        "site_id": action.site_id,
        "description": action.action_taken,
        "action_taken": action.action_taken,
        "assigned_to": str(action.assigned_to),
        "designation": action.designation,
        "status": action.status,
        "priority": action.priority,
        "due_date": action.due_date,
        "date_resolved": action.date_resolved,
        "created_at": action.created_at,
        "resolution_notes": action.resolution_notes,
        "resolved_by": action.resolved_by,
        "is_successful": action.is_successful,
    }


@router.get("/", response_model=List[CorrectiveActionResponse])
def get_all_corrective_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        actions = db.query(CorrectiveAction).filter(
            CorrectiveAction.site_id == current_user.site_id
        ).all()
    else:
        actions = db.query(CorrectiveAction).all()
    return [_to_response(action) for action in actions]

@router.get("/incident/{incident_id}", response_model=List[CorrectiveActionResponse])
def get_incident_corrective_actions(
    incident_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    actions = db.query(CorrectiveAction).filter(
        CorrectiveAction.incident_id == incident_id
    ).all()
    return [_to_response(action) for action in actions]


@router.get("/{action_id}", response_model=CorrectiveActionResponse)
def get_corrective_action(
    action_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")
    return _to_response(action)


@router.post("/", response_model=CorrectiveActionResponse)
def create_corrective_action(
    action_data: CorrectiveActionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = action_data.model_dump(exclude_unset=True)
    description = payload.get("description") or payload.get("action_taken")

    new_action = CorrectiveAction(
        incident_id=payload.get("incident_id"),
        site_id=payload.get("site_id"),
        assigned_to=payload.get("assigned_to"),
        action_taken=description,
        designation=payload.get("designation", "Safety"),
        priority=payload.get("priority", "medium"),
        status=payload.get("status", "open"),
        due_date=payload.get("due_date"),
    )

    db.add(new_action)
    db.commit()
    db.refresh(new_action)
    return _to_response(new_action)


# Resolution endpoint
@router.post("/{action_id}/resolve", response_model=CorrectiveActionResponse)
def resolve_corrective_action(
    action_id: int,
    resolve_data: CorrectiveActionResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")

    action.resolution_notes = resolve_data.resolution_notes
    action.is_successful = resolve_data.is_successful
    action.resolved_by = current_user.email
    action.date_resolved = datetime.utcnow()
    action.status = "resolved" if resolve_data.is_successful == "yes" else "open"

    db.commit()
    db.refresh(action)
    return _to_response(action)


@router.put("/{action_id}", response_model=CorrectiveActionResponse)
def update_corrective_action(
    action_id: int,
    action_data: CorrectiveActionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")

    updates = action_data.model_dump(exclude_unset=True)
    if "description" in updates and "action_taken" not in updates:
        updates["action_taken"] = updates.pop("description")

    allowed_fields = {"assigned_to", "action_taken", "status", "due_date", "date_resolved", "designation", "priority"}
    for key, value in updates.items():
        if key in allowed_fields:
            setattr(action, key, value)

    db.commit()
    db.refresh(action)
    return _to_response(action)


@router.delete("/{action_id}")
def delete_corrective_action(
    action_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team")),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")

    db.delete(action)
    db.commit()
    return {"message": "Corrective action deleted"}