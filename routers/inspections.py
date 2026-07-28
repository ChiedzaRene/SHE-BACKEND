import os
import uuid
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from database import get_db
from models.inspections import Inspection
from models.user import User
from schemas.inspections import InspectionResponse, InspectionUpdate
from services.auth_services import get_current_user

router = APIRouter(prefix="/inspections", tags=["Inspections"])

UPLOAD_DIR = "uploads/inspections"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/", response_model=List[InspectionResponse])
def get_all_inspections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        if current_user.role == "site_manager":
            return (
                db.query(Inspection)
                .filter(Inspection.site_id == current_user.site_id)
                .order_by(Inspection.inspection_date.desc())
                .all()
            )
        return db.query(Inspection).order_by(Inspection.inspection_date.desc()).all()
    except Exception as e:
        print(f"Error fetching inspections: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve inspections.",
        )


@router.get("/site/{site_id}", response_model=List[InspectionResponse])
def get_site_inspections(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return (
        db.query(Inspection)
        .filter(Inspection.site_id == site_id)
        .order_by(Inspection.inspection_date.desc())
        .all()
    )


@router.get("/{inspection_id}", response_model=InspectionResponse)
def get_inspection(
    inspection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")
    if current_user.role == "site_manager" and inspection.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Access denied")
    return inspection


@router.post("/", response_model=InspectionResponse)
async def create_inspection(
    site_id: int = Form(...),
    inspector_name: str = Form(""),
    inspection_date: date_type = Form(...),
    checklist_score: float = Form(0.0),
    she_file_score: float = Form(0.0),
    comments: Optional[str] = Form(""),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not (0 <= checklist_score <= 100) or not (0 <= she_file_score <= 100):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Checklist Score and SHE File Score must be between 0 and 100.",
        )

    file_url = None
    if file and file.filename:
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)

        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        file_url = f"/uploads/inspections/{unique_filename}"

    overall = round((checklist_score + she_file_score) / 2, 2)

    resolved_inspector = (
        inspector_name.strip()
        or getattr(current_user, "full_name", None)
        or current_user.username
    )

    inspection = Inspection(
        site_id=site_id,
        user_id=current_user.id,
        inspector_name=resolved_inspector,
        inspection_date=inspection_date,
        checklist_score=checklist_score,
        she_file_score=she_file_score,
        overall_score=overall,
        comments=comments or "",
        file_url=file_url,
    )
    db.add(inspection)
    db.commit()
    db.refresh(inspection)
    return inspection


@router.put("/{inspection_id}", response_model=InspectionResponse)
def update_inspection(
    inspection_id: int,
    data: InspectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")
    if current_user.role == "site_manager" and inspection.site_id != current_user.site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(inspection, key, value)

    if "checklist_score" in updates or "she_file_score" in updates:
        inspection.overall_score = round(
            (inspection.checklist_score + inspection.she_file_score) / 2, 2
        )

    db.commit()
    db.refresh(inspection)
    return inspection


@router.delete("/{inspection_id}")
def delete_inspection(
    inspection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "she_team"):
        raise HTTPException(status_code=403, detail="Access denied")
    inspection = db.query(Inspection).filter(Inspection.id == inspection_id).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="Inspection not found")
    db.delete(inspection)
    db.commit()
    return {"message": "Inspection deleted successfully"}