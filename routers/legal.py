from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.legal import Legal
from models.user import User
from schemas.legal import LegalCreate, LegalUpdate, LegalResponse
from services.auth_services import get_current_user, require_role
from typing import List

router = APIRouter(prefix="/legal", tags=["Legal"])

@router.get("/", response_model=List[LegalResponse])
def get_all_legal(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return db.query(Legal).filter(Legal.site_id == current_user.site_id).all()
    return db.query(Legal).all()

@router.get("/site/{site_id}", response_model=List[LegalResponse])
def get_site_legal(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return db.query(Legal).filter(Legal.site_id == site_id).all()

@router.get("/{legal_id}", response_model=LegalResponse)
def get_legal(
    legal_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    legal = db.query(Legal).filter(Legal.id == legal_id).first()
    if not legal:
        raise HTTPException(status_code=404, detail="Legal record not found")
    return legal

@router.post("/", response_model=LegalResponse)
def create_legal(
    legal_data: LegalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_legal = Legal(**legal_data.model_dump(), user_id=current_user.id)
    db.add(new_legal)
    db.commit()
    db.refresh(new_legal)
    return new_legal

@router.put("/{legal_id}", response_model=LegalResponse)
def update_legal(
    legal_id: int,
    legal_data: LegalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team"))
):
    legal = db.query(Legal).filter(Legal.id == legal_id).first()
    if not legal:
        raise HTTPException(status_code=404, detail="Legal record not found")
    for key, value in legal_data.model_dump(exclude_unset=True).items():
        setattr(legal, key, value)
    db.commit()
    db.refresh(legal)
    return legal