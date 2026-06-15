from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models.training import Training
from models.user import User
from schemas.training import TrainingCreate, TrainingUpdate, TrainingResponse
from services.auth_services import get_current_user, require_role
from typing import List

router = APIRouter(prefix="/trainings", tags=["Trainings"])

@router.get("/", response_model=List[TrainingResponse])
def get_all_trainings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager":
        return db.query(Training).filter(Training.site_id == current_user.site_id).all()
    return db.query(Training).all()

@router.get("/site/{site_id}", response_model=List[TrainingResponse])
def get_site_trainings(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return db.query(Training).filter(Training.site_id == site_id).all()

@router.get("/{training_id}", response_model=TrainingResponse)
def get_training(
    training_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    return training

@router.post("/", response_model=TrainingResponse)
def create_training(
    training_data: TrainingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_training = Training(**training_data.model_dump(), user_id=current_user.id)
    db.add(new_training)
    db.commit()
    db.refresh(new_training)
    return new_training

@router.put("/{training_id}", response_model=TrainingResponse)
def update_training(
    training_id: int,
    training_data: TrainingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    for key, value in training_data.model_dump(exclude_unset=True).items():
        setattr(training, key, value)
    db.commit()
    db.refresh(training)
    return training

@router.delete("/{training_id}")
def delete_training(
    training_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team"))
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    db.delete(training)
    db.commit()
    return {"message": "Training deleted"}