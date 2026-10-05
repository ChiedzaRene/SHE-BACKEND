from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from schemas.settings import SafetyTargets, SafetyTargetsUpdate
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role
from services.settings import get_safety_limits, safety_targets_payload, set_safety_limits

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/safety-targets", response_model=SafetyTargets)
def read_safety_targets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # every screen that flags sites needs these
):
    return safety_targets_payload(db)


@router.put("/safety-targets", response_model=SafetyTargets)
def update_safety_targets(
    request: Request,
    payload: SafetyTargetsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    before = get_safety_limits(db)
    set_safety_limits(db, current_user.id, payload.trir_limit, payload.ltifr_limit)
    log_action(
        db=db,
        user=current_user,
        action="UPDATE_SETTINGS",
        resource="settings",
        details=(
            f"TRIR limit {before['trir_limit']:g} -> {payload.trir_limit:g}; "
            f"LTIFR limit {before['ltifr_limit']:g} -> {payload.ltifr_limit:g}"
        ),
        ip_address=request.client.host if request.client else None,
    )
    return safety_targets_payload(db)
