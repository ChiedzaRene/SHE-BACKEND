from models.audit_log import AuditLog
from sqlalchemy.orm import Session

def log_action(
    db: Session,
    user,
    action: str,
    resource: str,
    resource_id: int = None,
    details: str = None,
    ip_address: str = None
):
    entry = AuditLog(
        user_email=user.email,
        user_role=user.role,
        action=action,
        resource=resource,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address
    )
    db.add(entry)
    db.commit()


def log_event(
    db: Session,
    *,
    email: str,
    role: str,
    action: str,
    resource: str,
    details: str = None,
    ip_address: str = None,
):
    """Like log_action, for someone who isn't (or isn't yet) a signed-in user, e.g. a failed sign-in.

    The email is whatever was typed, so it is cut to a sane length before it is stored.
    """
    db.add(AuditLog(
        user_email=(email or "")[:254],
        user_role=role,
        action=action,
        resource=resource,
        details=details,
        ip_address=ip_address,
    ))
    db.commit()