# audit_log.py
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from models.audit_log import AuditLog
from models.user import User
from schemas.audit_log import AuditLogResponse
from services.audit_service import log_action
from services.auth_services import require_role
from services.report_render import to_pdf
from services.reports import AUDIT_EXPORT_MAX_ROWS, audit_log_document

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def _like_escape(text: str) -> str:
    """Make %, _ and \\ in a search box match literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply_filters(query, user, resource, action, start, end):
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
    return query


def _describe_filters(user, resource, action, start, end) -> str:
    parts = [f"user contains '{user}'" if user else "", f"action {action}" if action else "",
             f"area {resource}" if resource else "",
             f"from {start.isoformat()}" if start else "", f"to {end.isoformat()}" if end else ""]
    return ", ".join(p for p in parts if p)


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
    query = _apply_filters(db.query(AuditLog), user, resource, action, start, end)

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


@router.get("/export")
def export_audit_log(
    request: Request,
    user: Optional[str] = Query(None, max_length=100),
    resource: Optional[str] = Query(None, max_length=100),
    action: Optional[str] = Query(None, max_length=100),
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    """The audit log as a PDF, using the same filters as the list (Super Admin only)."""
    query = _apply_filters(db.query(AuditLog), user, resource, action, start, end)
    total = query.count()
    entries = query.order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(AUDIT_EXPORT_MAX_ROWS).all()
    filter_text = _describe_filters(user, resource, action, start, end)
    pdf = to_pdf(audit_log_document(entries, total, filter_text))

    # Exporting who-did-what is itself something worth recording
    log_action(
        db=db,
        user=current_user,
        action="EXPORT_AUDIT_LOG",
        resource="audit_logs",
        details=f"Exported {len(entries)} of {total} entries" + (f" ({filter_text})" if filter_text else ""),
        ip_address=request.client.host if request.client else None,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="she-audit-log-{date.today().isoformat()}.pdf"'},
    )
