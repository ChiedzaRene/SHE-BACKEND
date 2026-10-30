import re
import uuid
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


def _out(t: Training, sessions: Optional[dict] = None) -> TrainingResponse:
    out = TrainingResponse.model_validate(t)
    out.has_document = bool(t.document_name)
    out.document_viewable = bool(t.document_name) and is_viewable(t.document_name)
    out.session_sites = (sessions or {}).get(t.session_id, [t.site_id]) if t.session_id else [t.site_id]
    return out


def _sessions(db: Session, rows) -> dict:
    """session id -> the sites given that training together."""
    ids = {t.session_id for t in rows if t.session_id}
    out: dict = {}
    if ids:
        for sid, site_id in db.query(Training.session_id, Training.site_id).filter(Training.session_id.in_(ids)) \
                .order_by(Training.id):
            out.setdefault(sid, []).append(site_id)
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
    rows = page.apply(query, response).all()
    sessions = _sessions(db, rows)
    return [_out(t, sessions) for t in rows]


@router.get("/site/{site_id}", response_model=List[TrainingResponse])
def get_site_trainings(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_visible(db, current_user, site_id)
    rows = db.query(Training).filter(Training.site_id == site_id).order_by(Training.date.desc()).all()
    sessions = _sessions(db, rows)
    return [_out(t, sessions) for t in rows]


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
    return _out(training, _sessions(db, [training]))


@router.post("/record", response_model=TrainingResponse, status_code=201)
async def record_training(
    request: Request,
    site_id: List[int] = Form(..., description="one or more sites trained together"),
    training_date: date = Form(..., alias="date"),
    training_module: str = Form(..., min_length=2, max_length=200),
    trainer_name: str = Form(..., min_length=2, max_length=150),
    personnel: str = Form(..., min_length=2, max_length=2000, description="the people trained"),
    trained_employees: List[int] = Form(..., description="how many were trained at each site, in the same order"),
    type: Optional[str] = Form(None, max_length=100),
    comments: Optional[str] = Form(None, max_length=2000),
    video_link: Optional[str] = Form(None, max_length=1000, description="for an online training: its recording"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("she_team", "she_officer", "admin", "super_admin")),
):
    """A training given by the SHE team (fire fighting, first aid...), with its supporting document.

    One training can be given to several sites at once: each site gets its own record (so its managers see it,
    and its reports count only its own people), all sharing one session id.

    A training given online can carry the link to its recording (the OneDrive folder with the video) instead of,
    or as well as, a document.
    """
    site_ids = list(dict.fromkeys(site_id))
    if len(site_ids) != len(site_id):
        raise HTTPException(status_code=422, detail="Each site can only be chosen once.")
    if len(site_ids) > 50:
        raise HTTPException(status_code=422, detail="A training can be recorded for at most 50 sites at once.")
    if len(trained_employees) != len(site_ids):
        raise HTTPException(status_code=422, detail="Enter how many people were trained at each site.")
    if any(n < 1 or n > 100_000 for n in trained_employees):
        raise HTTPException(status_code=422, detail="Enter how many people were trained at each site (at least 1).")
    known = {sid for (sid,) in db.query(Site.id).filter(Site.id.in_(site_ids))}
    if len(known) != len(site_ids):
        raise HTTPException(status_code=404, detail="Site not found")
    if training_date > local_today():
        raise HTTPException(status_code=422, detail="The training date can't be in the future.")
    link = (video_link or "").strip() or None
    if link and not re.match(r"^https://[^\s<>\"']+$", link):
        raise HTTPException(status_code=422, detail="The recording link must be a full https:// web address.")
    if file is None and not link:
        raise HTTPException(status_code=422, detail="Attach the supporting document, or give the link to the recording.")
    filename = content_type = data = None
    if file is not None:
        filename, content_type = clean_filename(file)
        data = await read_upload(file)
    module, trainer, people = (sanitize_text(v) for v in (training_module, trainer_name, personnel))
    if len(module or "") < 2 or len(trainer or "") < 2 or len(people or "") < 2:
        raise HTTPException(status_code=422, detail="Fill in the training, the trainer and the people trained.")
    session = str(uuid.uuid4()) if len(site_ids) > 1 else None
    records = [
        Training(
            site_id=sid, user_id=current_user.id, training_module=module, trainer_name=trainer, personnel=people,
            trained_employees=count, total_employees=count,
            date=datetime.combine(training_date, datetime.min.time()), type=sanitize_text(type) or None,
            comments=sanitize_text(comments) or None, document_name=filename, document_type=content_type,
            document_size=len(data) if data is not None else None, document=data, video_link=link, session_id=session,
        )
        for sid, count in zip(site_ids, trained_employees)
    ]
    db.add_all(records)
    db.commit()
    for training, count in zip(records, trained_employees):
        db.refresh(training)
        where = site_name(db, training.site_id)
        log_action(db=db, user=current_user, action="CREATE_TRAINING", resource="trainings", resource_id=training.id,
                   details=f"Recorded \"{short(module, 80)}\" at {where} on {training_date.isoformat()}: "
                           f"{count} trained by {trainer} ({filename or 'recording link'})"
                           + (f"; given to {len(records)} sites together" if session else ""),
                   ip_address=request.client.host if request.client else None)
        notify(db, site_managers(db, training.site_id), kind="training_recorded",
               title=f"Training recorded at {where}: {short(module, 120)}",
               message=f"{who(current_user)} recorded {count} people trained by {trainer}",
               link="/trainings", resource="trainings", resource_id=training.id, actor=current_user)
    return _out(records[0], {session: site_ids} if session else None)


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