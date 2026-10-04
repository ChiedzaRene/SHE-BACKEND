# audit_log.py
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from database import get_db
from models.audit_log import AuditLog
from models.user import User
from schemas.audit_log import AuditLogResponse
from services.auth_services import require_role

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def _like_escape(text: str) -> str:
    """Make %, _ and \\ in a search box match literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/", response_model=List[AuditLogResponse])
def get_audit_logs(
    response: Response,
    user: Optional[str] = Query(None, max_length=100, description="Part of the user's email"),
    resource: Optional[str] = Query(None, max_length=100),
    action: Optional[str] = Query(None, max_length=100),
    start: Optional[date] = Query(None, description="First day"),
    end: Optional[date] = Query(None, description="Last day"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    # Strict Super Admin Restriction:
    current_user: User = Depends(require_role("super_admin")),
):
    """Retrieve system audit logs, newest first (Super Admin only). Total matches in X-Total-Count."""
    query = db.query(AuditLog)

    if user:
        query = query.filter(AuditLog.user_email.ilike(f"%{_like_escape(user)}%", escape="\\"))
    if resource:
        query = query.filter(AuditLog.resource == resource)
    if action:
        query = query.filter(AuditLog.action == action)
    if start:
        query = query.filter(AuditLog.timestamp >= start)
    if end:
        query = query.filter(AuditLog.timestamp < end + timedelta(days=1))

    response.headers["X-Total-Count"] = str(query.count())
    return (
        query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


@router.get("/facets")
def get_audit_log_facets(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    """The actions and resources that appear in the log, for the filter dropdowns."""
    return {
        "actions": [a for (a,) in db.query(AuditLog.action).distinct().order_by(AuditLog.action)],
        "resources": [r for (r,) in db.query(AuditLog.resource).distinct().order_by(AuditLog.resource)],
    }
