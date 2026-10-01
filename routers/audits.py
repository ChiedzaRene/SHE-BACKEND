from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from models.audit import Audit
from models.user import User
from schemas.audit import AuditCreate, AuditResponse, AuditUpdate
from services.audit_service import log_action
from services.access import assert_site_access
from services.pagination import Pagination
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/audits", tags=["Audits"])


@router.get("/", response_model=List[AuditResponse])
def get_all_audits(
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Audit)
    if current_user.role == "site_manager":
        query = query.filter(Audit.site_id == current_user.site_id)
    return page.apply(query, response, Audit.id).all()


@router.get("/site/{site_id}", response_model=List[AuditResponse])
def get_site_audits(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)
    return db.query(Audit).filter(Audit.site_id == site_id).all()


@router.get("/{audit_id}", response_model=AuditResponse)
def get_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    assert_site_access(current_user, audit.site_id)
    return audit


@router.post("/", response_model=AuditResponse)
def create_audit(
    request: Request,
    audit_data: AuditCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and audit_data.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Cannot create audits for other sites")

    new_audit = Audit(**audit_data.model_dump(), user_id=current_user.id)
    db.add(new_audit)
    db.commit()
    db.refresh(new_audit)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_AUDIT",
        resource="audits",
        resource_id=new_audit.id,
        details=f"Created audit ID #{new_audit.id} for site #{new_audit.site_id}",
        ip_address=request.client.host,
    )
    return new_audit


@router.put("/{audit_id}", response_model=AuditResponse)
def update_audit(
    request: Request,
    audit_id: int,
    audit_data: AuditUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team")),
):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")

    for key, value in audit_data.model_dump(exclude_unset=True).items():
        setattr(audit, key, value)

    db.commit()
    db.refresh(audit)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_AUDIT",
        resource="audits",
        resource_id=audit.id,
        details=f"Updated audit #{audit.id}",
        ip_address=request.client.host,
    )
    return audit