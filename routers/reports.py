from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from services import reports as builders
from services.audit_service import log_action
from services.auth_services import get_current_user
from services.report_render import to_csv, to_pdf

router = APIRouter(prefix="/reports", tags=["Reports"])

Kind = Literal["performance", "compliance", "incidents", "leaderboard"]
MEDIA = {"csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


@router.get("/{kind}")
def get_report(
    request: Request,
    kind: Kind,
    site_id: Optional[int] = Query(None, gt=0, description="Omit for all sites"),
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="performance: YYYY-MM"),
    start: Optional[date] = Query(None, description="incidents: first day"),
    end: Optional[date] = Query(None, description="incidents: last day"),
    type: Optional[str] = Query(None, max_length=50, description="incidents: type filter"),
    severity: Optional[str] = Query(None, pattern="^(?i:low|medium|high|critical)$", description="incidents: severity filter"),
    period: str = Query("12m", pattern="^(12m|ytd)$", description="leaderboard window"),
    format: Literal["json", "csv", "pdf"] = "json",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        # Cross-site comparison is for the SHE team; a manager only ever reports on their own site
        if kind == "leaderboard":
            raise HTTPException(status_code=403, detail="Site comparison is not available to site managers")
        if site_id is not None and site_id != current_user.site_id:
            raise HTTPException(status_code=403, detail="Access denied")
        site_id = current_user.site_id

    try:
        if kind == "performance":
            doc = builders.performance_report(db, site_id, month)
        elif kind == "compliance":
            doc = builders.compliance_report(db, site_id)
        elif kind == "incidents":
            doc = builders.incident_register(db, site_id, start, end, type, severity)
        else:
            doc = builders.leaderboard_report(db, period)
    except builders.ReportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if format == "json":
        return doc

    body = to_csv(doc) if format == "csv" else to_pdf(doc)
    # Exports leave the system, so they are recorded in the audit log
    log_action(
        db=db,
        user=current_user,
        action="EXPORT_REPORT",
        resource="reports",
        details=f"{kind} ({format.upper()}): {doc['subtitle']}",
        ip_address=request.client.host if request.client else None,
    )
    slug = "".join(ch if ch.isalnum() else "-" for ch in f"{kind}-{doc['subtitle']}").strip("-").lower()
    slug = "-".join(part for part in slug.split("-") if part)[:80]
    return Response(
        content=body,
        media_type=MEDIA[format],
        headers={"Content-Disposition": f'attachment; filename="she-{slug}.{format}"'},
    )
