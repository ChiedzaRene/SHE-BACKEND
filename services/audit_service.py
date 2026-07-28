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