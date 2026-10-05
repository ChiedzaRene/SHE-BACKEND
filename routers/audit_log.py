# audit_log.py
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models.user import User as UserModel
from models.audit_log import AuditLog
from models.user import User
from schemas.audit_log import AuditLogResponse
from services.audit_labels import ACTION_LABELS, RESOURCE_LABELS, action_label, resource_label
from services.auth_services import require_role

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def _like_escape(text: str) -> str:
    """Make %, _ and \\ in a search box match literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _apply_filters(query, user, resource, action, start, end, email=None):
    if email:
        # A person picked from the list: exactly their address, never someone whose address merely contains it
        query = query.filter(func.lower(AuditLog.user_email) == email.strip().lower())
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


@router.get("/", response_model=List[AuditLogResponse])
def get_audit_logs(
    response: Response,
    email: Optional[str] = Query(None, max_length=254, description="Exactly this person (as picked from the list)"),
    user: Optional[str] = Query(None, max_length=100, description="Part of an email (a looser search)"),
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
    query = _apply_filters(db.query(AuditLog), user, resource, action, start, end, email)

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
    """The actions, areas and people that appear in the log, with plain-English names, for the filters."""
    actions = [a for (a,) in db.query(AuditLog.action).distinct()]
    resources = [r for (r,) in db.query(AuditLog.resource).distinct()]
    return {
        # sorted by the name people will read, not by the code
        "actions": sorted(actions, key=lambda a: action_label(a).lower()),
        "action_labels": {a: action_label(a) for a in set(actions) | set(ACTION_LABELS)},
        "resources": sorted(resources, key=lambda r: resource_label(r).lower()),
        "resource_labels": {r: resource_label(r) for r in set(resources) | set(RESOURCE_LABELS)},
        "users": _people(db),
    }


def _people(db: Session) -> list:
    """Everyone who can appear in the log: all accounts, plus anyone since deleted (their entries remain)."""
    people = {}
    for u in db.query(UserModel).all():
        people[u.email.lower()] = {
            "email": u.email, "name": u.full_name or "", "role": u.role,
            "status": "active" if u.is_active else "inactive",
        }
    # People in the log who no longer have an account (deleted) or never did (a mistyped sign-in)
    for email, role in db.query(AuditLog.user_email, AuditLog.user_role).distinct():
        if email and email.lower() not in people:
            people[email.lower()] = {"email": email, "name": "", "role": role, "status": "removed"}
    return sorted(people.values(), key=lambda p: (p["name"] or p["email"]).lower())


@router.get("/person")
def get_person_summary(
    email: str = Query(..., max_length=254),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    """Everything about one person's trail at a glance: how much, since when, and what kind of activity."""
    mine = func.lower(AuditLog.user_email) == email.strip().lower()
    total, first_at, last_at = db.query(func.count(AuditLog.id), func.min(AuditLog.timestamp), func.max(AuditLog.timestamp)).filter(mine).one()
    last_sign_in = db.query(func.max(AuditLog.timestamp)).filter(mine, AuditLog.action == "LOGIN").scalar()
    failed = db.query(func.count(AuditLog.id)).filter(mine, AuditLog.action == "LOGIN_FAILED").scalar()
    by_activity = (
        db.query(AuditLog.action, func.count(AuditLog.id))
        .filter(mine).group_by(AuditLog.action).order_by(func.count(AuditLog.id).desc()).all()
    )
    info = next((p for p in _people(db) if p["email"].lower() == email.strip().lower()), None)
    return {
        "email": info["email"] if info else email.strip(),
        "name": info["name"] if info else "",
        "role": info["role"] if info else None,
        "status": info["status"] if info else "unknown",
        "total": total,
        "first_at": first_at,
        "last_at": last_at,
        "last_sign_in_at": last_sign_in,
        "failed_sign_ins": failed,
        "by_activity": [{"action": a, "label": action_label(a), "count": c} for a, c in by_activity],
    }
