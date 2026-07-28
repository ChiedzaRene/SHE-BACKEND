# audit_log.py
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models.audit_log import AuditLog
from models.user import User
from schemas.audit_log import AuditLogResponse
from services.auth_services import require_role

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


@router.get("/", response_model=List[AuditLogResponse])
def get_audit_logs(
    resource: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    # Strict Super Admin Restriction:
    current_user: User = Depends(require_role("super_admin")),
):
    """Retrieve system audit logs (Super Admin only)."""
    query = db.query(AuditLog)

    if resource:
        query = query.filter(AuditLog.resource == resource)
    if action:
        query = query.filter(AuditLog.action == action)

    return query.order_by(AuditLog.timestamp.desc()).limit(500).all()