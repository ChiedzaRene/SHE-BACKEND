from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from database import get_db
from models.legal import Legal
from models.user import User
from schemas.legal import LegalCreate, LegalResponse, LegalUpdate
from services.audit_service import log_action
from services.access import assert_site_access
from services.pagination import Pagination
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/legal", tags=["Legal"])


@router.get("/", response_model=List[LegalResponse])
def get_all_legal(
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Legal)
    if current_user.role == "site_manager":
        query = query.filter(Legal.site_id == current_user.site_id)
    return page.apply(query, response, Legal.id).all()


@router.get("/site/{site_id}", response_model=List[LegalResponse])
def get_site_legal(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)
    return db.query(Legal).filter(Legal.site_id == site_id).all()


@router.get("/{legal_id}", response_model=LegalResponse)
def get_legal(
    legal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    legal = db.query(Legal).filter(Legal.id == legal_id).first()
    if not legal:
        raise HTTPException(status_code=404, detail="Legal record not found")
    assert_site_access(current_user, legal.site_id)
    return legal


@router.post("/", response_model=LegalResponse)
def create_legal(
    request: Request,
    legal_data: LegalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and legal_data.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Cannot create legal records for other sites")

    new_legal = Legal(**legal_data.model_dump(), user_id=current_user.id)
    db.add(new_legal)
    db.commit()
    db.refresh(new_legal)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_LEGAL_RECORD",
        resource="legal",
        resource_id=new_legal.id,
        details=f"Created legal record #{new_legal.id}",
        ip_address=request.client.host,
    )
    return new_legal


@router.put("/{legal_id}", response_model=LegalResponse)
def update_legal(
    request: Request,
    legal_id: int,
    legal_data: LegalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team")),
):
    legal = db.query(Legal).filter(Legal.id == legal_id).first()
    if not legal:
        raise HTTPException(status_code=404, detail="Legal record not found")

    for key, value in legal_data.model_dump(exclude_unset=True).items():
        setattr(legal, key, value)

    db.commit()
    db.refresh(legal)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_LEGAL_RECORD",
        resource="legal",
        resource_id=legal.id,
        details=f"Updated legal record #{legal.id}",
        ip_address=request.client.host,
    )
    return legal