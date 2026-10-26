from datetime import date, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy.orm import Session, undefer

from database import get_db
from models.site import Site
from models.training import Training
from models.user import User
from schemas.training import TrainingCreate, TrainingResponse, TrainingUpdate, sanitize_text
from services.clock import local_today
from services.files import clean_filename, file_response, is_viewable, read_upload
from services.notifications import notify, short, site_managers, site_name, who
from services.audit_service import log_action
from services.access import assert_site_access, assert_site_visible, region_site_ids
from services.pagination import Pagination
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/trainings", tags=["Trainings"])


def _out(t: Training) -> TrainingResponse:
    out = TrainingResponse.model_validate(t)
    out.has_document = bool(t.document_name)
    out.document_viewable = bool(t.document_name) and is_viewable(t.document_name)
    return out


@router.get("/", response_model=List[TrainingResponse])
def get_all_trainings(
    response: Response,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Training)
    if current_user.role == "site_manager":
        query = query.filter(Training.site_id == current_user.site_id)
    mine = region_site_ids(db, current_user)
    if mine is not None:  # a regional manager sees the trainings at the sites in their region
        query = query.filter(Training.site_id.in_(mine or [0]))
    query = query.order_by(Training.date.desc(), Training.id.desc())  # newest first
    return [_out(t) for t in page.apply(query, response).all()]


@router.get("/site/{site_id}", response_model=List[TrainingResponse])
def get_site_trainings(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_visible(db, current_user, site_id)
    return [_out(t) for t in db.query(Training).filter(Training.site_id == site_id).order_by(Training.date.desc()).all()]


@router.get("/{training_id}", response_model=TrainingResponse)
def get_training(
    training_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    training = db.query(Training).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    assert_site_visible(db, current_user, training.site_id)
    return _out(training)


@router.post("/record", response_model=TrainingResponse, status_code=201)
async def record_training(
    request: Request,
    site_id: int = Form(..., gt=0),
    training_date: date = Form(..., alias="date"),
    training_module: str = Form(..., min_length=2, max_length=200),
    trainer_name: str = Form(..., min_length=2, max_length=150),
    personnel: str = Form(..., min_length=2, max_length=2000, description="the people trained"),
    trained_employees: int = Form(..., ge=1, le=100_000),
    type: Optional[str] = Form(None, max_length=100),
    comments: Optional[str] = Form(None, max_length=2000),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("she_team", "she_officer", "admin", "super_admin")),
):
    """A training given by the SHE team (fire fighting, first aid...), with its supporting document."""
    if not db.query(Site.id).filter(Site.id == site_id).first():
        raise HTTPException(status_code=404, detail="Site not found")
    if training_date > local_today():
        raise HTTPException(status_code=422, detail="The training date can't be in the future.")
    filename, content_type = clean_filename(file)
    data = await read_upload(file)
    module, trainer, people = (sanitize_text(v) for v in (training_module, trainer_name, personnel))
    if len(module or "") < 2 or len(trainer or "") < 2 or len(people or "") < 2:
        raise HTTPException(status_code=422, detail="Fill in the training, the trainer and the people trained.")
    training = Training(
        site_id=site_id, user_id=current_user.id, training_module=module, trainer_name=trainer, personnel=people,
        trained_employees=trained_employees, total_employees=trained_employees,
        date=datetime.combine(training_date, datetime.min.time()), type=sanitize_text(type) or None,
        comments=sanitize_text(comments) or None, document_name=filename, document_type=content_type,
        document_size=len(data), document=data,
    )
    db.add(training)
    db.commit()
    db.refresh(training)
    log_action(db=db, user=current_user, action="CREATE_TRAINING", resource="trainings", resource_id=training.id,
               details=f"Recorded \"{short(module, 80)}\" at {site_name(db, site_id)} on {training_date.isoformat()}: "
                       f"{trained_employees} trained by {trainer} ({filename})",
               ip_address=request.client.host if request.client else None)
    notify(db, site_managers(db, site_id), kind="training_recorded",
           title=f"Training recorded at {site_name(db, site_id)}: {short(module, 120)}",
           message=f"{who(current_user)} recorded {trained_employees} people trained by {trainer}",
           link="/trainings", resource="trainings", resource_id=training.id, actor=current_user)
    return _out(training)


def _with_document(db: Session, user: User, training_id: int) -> Training:
    training = db.query(Training).options(undefer(Training.document)).filter(Training.id == training_id).first()
    if not training:
        raise HTTPException(status_code=404, detail="Training not found")
    assert_site_visible(db, user, training.site_id)
    if not training.document_name or training.document is None:
        raise HTTPException(status_code=404, detail="This training has no document")
    return training


@router.get("/{training_id}/document/view")
def view_training_document(training_id: int, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    t = _with_document(db, current_user, training_id)
    if not is_viewable(t.document_name):
        raise HTTPException(status_code=415, detail="This type of file can't be shown in the app. Download it instead.")
    return file_response(t.document, t.document_type, t.document_name, "inline")


@router.get("/{training_id}/document")
def download_training_document(training_id: int, db: Session = Depends(get_db),
                               current_user: User = Depends(get_current_user)):
    t = _with_document(db, current_user, training_id)
    return file_response(t.document, t.document_type, t.document_name, "attachment")


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
    return _out(new_training)


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
    assert_site_access(current_user, training.site_id)

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
    return _out(training)


@router.delete("/{training_id}")
def delete_training(
    request: Request,
    training_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin", "she_team", "she_officer")),
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