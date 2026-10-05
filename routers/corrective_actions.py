from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from models.corrective_action import CorrectiveAction
from models.user import User
from schemas.corrective_action import (
    CorrectiveActionCreate,
    CorrectiveActionResolve,
    CorrectiveActionResponse,
    CorrectiveActionUpdate,
)
from services.audit_service import log_action
from services.notifications import find_person, notify, short, site_managers, site_name, team, who
from services.access import assert_site_access
from services.pagination import Pagination
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/corrective-actions", tags=["Corrective Actions"])


def _notify_assignee(db: Session, action: CorrectiveAction, actor: User) -> None:
    """Tell the person the action is assigned to (when the name matches an account), and the site's manager."""
    where = site_name(db, action.site_id)
    due = f" Due {action.due_date:%d %b %Y}." if action.due_date else ""
    assignee = find_person(db, action.assigned_to)
    if assignee:
        notify(
            db, [assignee], kind="action_assigned",
            title=f"Corrective action assigned to you at {where}",
            message=f"{who(actor)} assigned you: {short(action.action_taken)}.{due}",
            link="/corrective-actions", resource="corrective_actions", resource_id=action.id, actor=actor,
        )
    managers = [m for m in site_managers(db, action.site_id) if not assignee or m.id != assignee.id]
    notify(
        db, managers, kind="action_created",
        title=f"Corrective action at {where} assigned to {action.assigned_to}",
        message=f"{short(action.action_taken)}.{due}",
        link="/corrective-actions", resource="corrective_actions", resource_id=action.id, actor=actor,
    )


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
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(CorrectiveAction)
    if current_user.role == "site_manager":
        query = query.filter(CorrectiveAction.site_id == current_user.site_id)
    actions = page.apply(query, response, CorrectiveAction.id.desc()).all()
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

    if current_user.role == "site_manager":
        actions = [a for a in actions if a.site_id == current_user.site_id]

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
    assert_site_access(current_user, action.site_id)
    return _to_response(action)


@router.post("/", response_model=CorrectiveActionResponse)
def create_corrective_action(
    request: Request,
    action_data: CorrectiveActionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payload = action_data.model_dump(exclude_unset=True)
    if current_user.role == "site_manager" and payload.get("site_id") != current_user.site_id:
        raise HTTPException(status_code=403, detail="Cannot assign corrective action to another site")

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

    log_action(
        db=db,
        user=current_user,
        action="CREATE_CORRECTIVE_ACTION",
        resource="corrective_actions",
        resource_id=new_action.id,
        details=f"Created action item #{new_action.id} for incident #{new_action.incident_id}",
        ip_address=request.client.host,
    )
    _notify_assignee(db, new_action, current_user)
    return _to_response(new_action)


@router.post("/{action_id}/resolve", response_model=CorrectiveActionResponse)
def resolve_corrective_action(
    request: Request,
    action_id: int,
    resolve_data: CorrectiveActionResolve,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")
    assert_site_access(current_user, action.site_id)

    action.resolution_notes = resolve_data.resolution_notes
    action.is_successful = resolve_data.is_successful
    action.resolved_by = current_user.email
    action.date_resolved = datetime.utcnow()
    action.status = "resolved" if resolve_data.is_successful == "yes" else "open"

    db.commit()
    db.refresh(action)

    log_action(
        db=db,
        user=current_user,
        action="RESOLVE_CORRECTIVE_ACTION",
        resource="corrective_actions",
        resource_id=action.id,
        details=f"Resolved action #{action.id} (Success: {resolve_data.is_successful})",
        ip_address=request.client.host,
    )
    outcome = "resolved" if action.status == "resolved" else "reviewed but not effective (still open)"
    notify(
        db, team(db) + site_managers(db, action.site_id) + [find_person(db, action.assigned_to)],
        kind="action_resolved",
        title=f"Corrective action {outcome} at {site_name(db, action.site_id)}",
        message=f"{who(current_user)}: {short(action.action_taken)}",
        link="/corrective-actions", resource="corrective_actions", resource_id=action.id, actor=current_user,
    )
    return _to_response(action)


@router.put("/{action_id}", response_model=CorrectiveActionResponse)
def update_corrective_action(
    request: Request,
    action_id: int,
    action_data: CorrectiveActionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")
    assert_site_access(current_user, action.site_id)

    updates = action_data.model_dump(exclude_unset=True)
    if "description" in updates and "action_taken" not in updates:
        updates["action_taken"] = updates.pop("description")

    allowed_fields = {"assigned_to", "action_taken", "status", "due_date", "date_resolved", "designation", "priority"}
    previous_assignee = (action.assigned_to or "").strip().lower()
    for key, value in updates.items():
        if key in allowed_fields:
            setattr(action, key, value)

    db.commit()
    db.refresh(action)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_CORRECTIVE_ACTION",
        resource="corrective_actions",
        resource_id=action.id,
        details=f"Updated corrective action #{action.id}",
        ip_address=request.client.host,
    )
    if "assigned_to" in updates and (action.assigned_to or "").strip().lower() != previous_assignee:
        _notify_assignee(db, action, current_user)  # handed to someone new
    return _to_response(action)


@router.delete("/{action_id}")
def delete_corrective_action(
    request: Request,
    action_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team")),
):
    action = db.query(CorrectiveAction).filter(CorrectiveAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Corrective action not found")

    db.delete(action)
    db.commit()

    log_action(
        db=db,
        user=current_user,
        action="DELETE_CORRECTIVE_ACTION",
        resource="corrective_actions",
        resource_id=action_id,
        details=f"Deleted corrective action #{action_id}",
        ip_address=request.client.host,
    )
    return {"message": "Corrective action deleted"}