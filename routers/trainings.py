from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.training import Training
from models.user import User
from schemas.training import TrainingCreate, TrainingResponse, TrainingUpdate
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/trainings", tags=["Trainings"])


@router.get("/", response_model=List[TrainingResponse])
def get_all_trainings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        return db.query(Training).filter(Training.site_id == current_user.site_id).all()
    return db.query(Training).all()


@router.get("/site/{site_id}", response_model=List[TrainingResponse])
def get_site_trainings(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return db.query(Training).filter(Training.site_id == site_id).all()


@router.get("/{training_id}", response_model=TrainingResponse)
def get_training(
    training_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    if current_user.role == "site_manager" and training.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return training


@router.post("/", response_model=TrainingResponse)
def create_training(
    request: Request,
    training_data: TrainingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and training_data.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Cannot create training session for another site")

    new_training = Training(**training_data.model_dump(), user_id=current_user.id)
    db.add(new_training)
    db.commit()
    db.refresh(new_training)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_TRAINING",
        resource="trainings",
        resource_id=new_training.id,
        details=f"Created training session #{new_training.id}",
        ip_address=request.client.host,
    )
    return new_training


@router.put("/{training_id}", response_model=TrainingResponse)
def update_training(
    request: Request,
    training_id: int,
    training_data: TrainingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    if current_user.role == "site_manager" and training.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    for key, value in training_data.model_dump(exclude_unset=True).items():
        setattr(training, key, value)

    db.commit()
    db.refresh(training)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_TRAINING",
        resource="trainings",
        resource_id=training.id,
        details=f"Updated training session #{training.id}",
        ip_address=request.client.host,
    )
    return training


@router.delete("/{training_id}")
def delete_training(
    request: Request,
    training_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team")),
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")

    db.delete(training)
    db.commit()

    log_action(
        db=db,
        user=current_user,
        action="DELETE_TRAINING",
        resource="trainings",
        resource_id=training_id,
        details=f"Deleted training session #{training_id}",
        ip_address=request.client.host,
    )
    return {"message": "Training deleted"}