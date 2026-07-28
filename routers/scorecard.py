from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime

from database import get_db
from models.scorecard import Scorecard, ScorecardItem
from models.site import Site
from models.user import User
from schemas.scorecard import ScorecardCreate, ScorecardOut

router = APIRouter(prefix="/scorecard", tags=["Scorecard"])




@router.get("/", response_model=List[ScorecardOut])
def get_all_latest(
    site_id: Optional[int] = Query(None, description="Filter by site"),
    min_score: Optional[float] = Query(None, ge=0, le=5),
    max_score: Optional[float] = Query(None, ge=0, le=5),
    start_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    db: Session = Depends(get_db),
):
   
    # Subquery: latest submitted_at per site_id
    latest_sub = (
        db.query(
            Scorecard.site_id,
            func.max(Scorecard.submitted_at).label("max_submitted_at"),
        )
        .group_by(Scorecard.site_id)
        .subquery()
    )

    query = (
        db.query(Scorecard)
        .join(
            latest_sub,
            (Scorecard.site_id == latest_sub.c.site_id)
            & (Scorecard.submitted_at == latest_sub.c.max_submitted_at),
        )
        .options(
            joinedload(Scorecard.site),
            joinedload(Scorecard.submitted_by_user),
            joinedload(Scorecard.items),
        )
    )

    # Apply filters
    if site_id:
        query = query.filter(Scorecard.site_id == site_id)
    if min_score is not None:
        query = query.filter(Scorecard.overall_score >= min_score)
    if max_score is not None:
        query = query.filter(Scorecard.overall_score <= max_score)
    if start_date:
        try:
            query = query.filter(
                Scorecard.submitted_at >= datetime.fromisoformat(start_date)
            )
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
    if end_date:
        try:
            # Include the full end day
            end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59)
            query = query.filter(Scorecard.submitted_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD.")

    scorecards = query.order_by(desc(Scorecard.submitted_at)).all()

    # Build response with joined names
    result = []
    for sc in scorecards:
        result.append(
            ScorecardOut(
                id=sc.id,
                site_id=sc.site_id,
                site_name=sc.site.name if sc.site else None,
                submitted_by=sc.submitted_by,
                submitted_by_name=sc.submitted_by_user.name if sc.submitted_by_user else None,
                overall_score=sc.overall_score,
                overall_percent=sc.overall_percent,
                notes=sc.notes,
                submitted_at=sc.submitted_at,
                items=[
                    {
                        "id": item.id,
                        "scorecard_id": item.scorecard_id,
                        "requirement_ref": item.requirement_ref,
                        "requirement_text": item.requirement_text,
                        "score": item.score,
                        "comments": item.comments,
                    }
                    for item in sc.items
                ],
            )
        )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# GET /scorecard/all  — every submission (history view)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/all", response_model=List[ScorecardOut])
def get_all_submissions(
    site_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Scorecard)
        .options(
            joinedload(Scorecard.site),
            joinedload(Scorecard.submitted_by_user),
        )
        .order_by(desc(Scorecard.submitted_at))
    )
    if site_id:
        query = query.filter(Scorecard.site_id == site_id)

    scorecards = query.all()
    return [
        ScorecardOut(
            id=sc.id,
            site_id=sc.site_id,
            site_name=sc.site.name if sc.site else None,
            submitted_by=sc.submitted_by,
            submitted_by_name=sc.submitted_by_user.name if sc.submitted_by_user else None,
            overall_score=sc.overall_score,
            overall_percent=sc.overall_percent,
            notes=sc.notes,
            submitted_at=sc.submitted_at,
        )
        for sc in scorecards
    ]


# ──────────────────────────────────────────────────────────────────────────────
# GET /scorecard/{id}  — single scorecard with items
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{scorecard_id}", response_model=ScorecardOut)
def get_scorecard(scorecard_id: int, db: Session = Depends(get_db)):
    sc = (
        db.query(Scorecard)
        .options(
            joinedload(Scorecard.site),
            joinedload(Scorecard.submitted_by_user),
            joinedload(Scorecard.items),
        )
        .filter(Scorecard.id == scorecard_id)
        .first()
    )
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found")

    return ScorecardOut(
        id=sc.id,
        site_id=sc.site_id,
        site_name=sc.site.name if sc.site else None,
        submitted_by=sc.submitted_by,
        submitted_by_name=sc.submitted_by_user.name if sc.submitted_by_user else None,
        overall_score=sc.overall_score,
        overall_percent=sc.overall_percent,
        notes=sc.notes,
        submitted_at=sc.submitted_at,
        items=[
            {
                "id": item.id,
                "scorecard_id": item.scorecard_id,
                "requirement_ref": item.requirement_ref,
                "requirement_text": item.requirement_text,
                "score": item.score,
                "comments": item.comments,
            }
            for item in sc.items
        ],
    )


# ──────────────────────────────────────────────────────────────────────────────
# POST /scorecard/  — submit a new scorecard
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ScorecardOut, status_code=201)
def create_scorecard(payload: ScorecardCreate, db: Session = Depends(get_db)):
    # Validate site and user exist
    site = db.query(Site).filter(Site.id == payload.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    user = db.query(User).filter(User.id == payload.submitted_by).first()
    if not user:
        raise HTTPException(status_code=404, detail="Submitting user not found")

    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one scorecard item is required")

    # Calculate overall score from items
    total = sum(item.score for item in payload.items)
    overall_score = round(total / len(payload.items), 2)
    overall_percent = round((overall_score / 5) * 100, 1)

    sc = Scorecard(
        site_id=payload.site_id,
        submitted_by=payload.submitted_by,
        overall_score=overall_score,
        overall_percent=overall_percent,
        notes=payload.notes,
    )
    db.add(sc)
    db.flush()  # get sc.id before adding items

    for item_data in payload.items:
        item = ScorecardItem(
            scorecard_id=sc.id,
            **item_data.model_dump(),
        )
        db.add(item)

    db.commit()
    db.refresh(sc)

    return ScorecardOut(
        id=sc.id,
        site_id=sc.site_id,
        site_name=site.name,
        submitted_by=sc.submitted_by,
        submitted_by_name=user.name,
        overall_score=sc.overall_score,
        overall_percent=sc.overall_percent,
        notes=sc.notes,
        submitted_at=sc.submitted_at,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /scorecard/{id}
# ──────────────────────────────────────────────────────────────────────────────

@router.delete("/{scorecard_id}", status_code=204)
def delete_scorecard(scorecard_id: int, db: Session = Depends(get_db)):
    sc = db.query(Scorecard).filter(Scorecard.id == scorecard_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    db.delete(sc)
    db.commit()