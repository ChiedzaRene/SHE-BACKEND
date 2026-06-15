from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.audit import Audit
from models.user import User
from schemas.audit import AuditCreate, AuditUpdate, AuditResponse
from services.auth_services import get_current_user, require_role
from typing import List

router = APIRouter(prefix="/audits", tags=["Audits"])
@router.get("/", response_model=List[AuditResponse])
def get_all_audits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return db.query(Audit).filter(Audit.site_id == current_user.site_id).all()
    return db.query(Audit).all()

@router.get("/site/{site_id}", response_model=List[AuditResponse])
def get_site_audits(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return db.query(Audit).filter(Audit.site_id == site_id).all()

@router.get("/{audit_id}", response_model=AuditResponse)
def get_audit(
    audit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    return audit

@router.post("/", response_model=AuditResponse)
def create_audit(
    audit_data: AuditCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_audit = Audit(**audit_data.model_dump(), user_id=current_user.id)
    db.add(new_audit)
    db.commit()
    db.refresh(new_audit)
    return new_audit

@router.put("/{audit_id}", response_model=AuditResponse)
def update_audit(
    audit_id: int,
    audit_data: AuditUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team"))
):
    audit = db.query(Audit).filter(Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found")
    for key, value in audit_data.model_dump(exclude_unset=True).items():
        setattr(audit, key, value)
    db.commit()
    db.refresh(audit)
    return audit