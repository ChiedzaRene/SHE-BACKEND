"""Audit-log housekeeping: entries older than AUDIT_RETENTION_DAYS (default two years) are deleted."""
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models.audit_log import AuditLog

logger = logging.getLogger("she_portal")


def retention_days() -> int:
    try:
        return max(30, int(os.getenv("AUDIT_RETENTION_DAYS", "730")))  # never less than 30 days
    except ValueError:
        return 730


def purge_old_audit_logs(db: Session, days: int = None, now: datetime = None) -> int:
    """Delete audit entries older than `days`. Returns how many were removed."""
    days = retention_days() if days is None else days
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    removed = db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
    db.commit()
    if removed:
        logger.info("Audit log retention: removed %s entries older than %s days", removed, days)
    return removed
