from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload, selectinload

from database import get_db
from models.scorecard import Scorecard, ScorecardItem
from models.site import Site
from models.user import User
from schemas.scorecard import ScorecardCreate, ScorecardOut
from services.access import assert_site_access
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/scorecard", tags=["Scorecard"])


def _to_out(sc: Scorecard, include_items: bool = True) -> ScorecardOut:
    return ScorecardOut(
        id=sc.id,
        site_id=sc.site_id,
        site_name=sc.site.name if sc.site else None,
        submitted_by=sc.submitted_by,
        submitted_by_name=sc.submitted_by_user.full_name if sc.submitted_by_user else None,
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
        ] if include_items else [],
    )


def _base_query(db: Session, with_items: bool = True):
    query = db.query(Scorecard).options(
        joinedload(Scorecard.site),
        joinedload(Scorecard.submitted_by_user),
    )
    if with_items:
        # selectinload avoids the row multiplication a joined collection causes
        query = query.options(selectinload(Scorecard.items))
    return query


# ──────────────────────────────────────────────────────────────────────────────
# GET /scorecard/  — latest scorecard per site (supports filters)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[ScorecardOut])
def get_all_latest(
    site_id: Optional[int] = Query(None, description="Filter by site"),
    min_score: Optional[float] = Query(None, ge=0, le=5),
    max_score: Optional[float] = Query(None, ge=0, le=5),
    start_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Site managers only ever see their own site
    if current_user.role == "site_manager":
        site_id = current_user.site_id

    latest_sub = (
        db.query(
            Scorecard.site_id,
            func.max(Scorecard.submitted_at).label("max_submitted_at"),
        )
        .group_by(Scorecard.site_id)
        .subquery()
    )

    query = _base_query(db).join(
        latest_sub,
        (Scorecard.site_id == latest_sub.c.site_id)
        & (Scorecard.submitted_at == latest_sub.c.max_submitted_at),
    )

    if site_id:
        query = query.filter(Scorecard.site_id == site_id)
    if min_score is not None:
        query = query.filter(Scorecard.overall_score >= min_score)
    if max_score is not None:
        query = query.filter(Scorecard.overall_score <= max_score)
    if start_date:
        try:
            query = query.filter(Scorecard.submitted_at >= datetime.fromisoformat(start_date))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD.")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date).replace(hour=23, minute=59, second=59)
            query = query.filter(Scorecard.submitted_at <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD.")

    return [_to_out(sc) for sc in query.order_by(desc(Scorecard.submitted_at)).all()]


# ──────────────────────────────────────────────────────────────────────────────
# GET /scorecard/all  — every submission (history view)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/all", response_model=List[ScorecardOut])
def get_all_submissions(
    site_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager":
        site_id = current_user.site_id

    query = _base_query(db, with_items=False).order_by(desc(Scorecard.submitted_at))
    if site_id:
        query = query.filter(Scorecard.site_id == site_id)
    return [_to_out(sc, include_items=False) for sc in query.all()]


# ──────────────────────────────────────────────────────────────────────────────
# GET /scorecard/site/{site_id}/latest and /scorecard/site/{site_id}
# (used by LegalCompliance.js and the history view)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/site/{site_id}/latest", response_model=ScorecardOut)
def get_site_latest(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)
    sc = (
        _base_query(db)
        .filter(Scorecard.site_id == site_id)
        .order_by(desc(Scorecard.submitted_at))
        .first()
    )
    if not sc:
        raise HTTPException(status_code=404, detail="No scorecard found for this site")
    return _to_out(sc)


@router.get("/site/{site_id}", response_model=List[ScorecardOut])
def get_site_history(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)
    query = (
        _base_query(db, with_items=False)
        .filter(Scorecard.site_id == site_id)
        .order_by(desc(Scorecard.submitted_at))
    )
    return [_to_out(sc, include_items=False) for sc in query.all()]


# ──────────────────────────────────────────────────────────────────────────────
# GET /scorecard/{id}  — single scorecard with items
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/{scorecard_id}", response_model=ScorecardOut)
def get_scorecard(
    scorecard_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sc = _base_query(db).filter(Scorecard.id == scorecard_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    assert_site_access(current_user, sc.site_id)
    return _to_out(sc)


# ──────────────────────────────────────────────────────────────────────────────
# POST /scorecard/  — submit a new scorecard
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=ScorecardOut, status_code=201)
def create_scorecard(
    request: Request,
    payload: ScorecardCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, payload.site_id)

    site = db.query(Site).filter(Site.id == payload.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    if not payload.items:
        raise HTTPException(status_code=400, detail="At least one scorecard item is required")

    total = sum(item.score for item in payload.items)
    overall_score = round(total / len(payload.items), 2)
    overall_percent = round((overall_score / 5) * 100, 1)

    sc = Scorecard(
        site_id=payload.site_id,
        # Always the authenticated user; never trust a client-supplied submitter
        submitted_by=current_user.id,
        overall_score=overall_score,
        overall_percent=overall_percent,
        notes=payload.notes,
    )
    db.add(sc)
    db.flush()  # get sc.id before adding items

    for item_data in payload.items:
        db.add(ScorecardItem(scorecard_id=sc.id, **item_data.model_dump()))

    db.commit()
    log_action(db=db, user=current_user, action="CREATE_SCORECARD", resource="scorecards", resource_id=sc.id,
               details=f"Scorecard for site #{payload.site_id}: {overall_percent}% over {len(payload.items)} requirements",
               ip_address=request.client.host if request.client else None)
    return _to_out(_base_query(db).filter(Scorecard.id == sc.id).one())


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /scorecard/{id}
# ──────────────────────────────────────────────────────────────────────────────

@router.delete("/{scorecard_id}", status_code=204)
def delete_scorecard(
    request: Request,
    scorecard_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    sc = db.query(Scorecard).filter(Scorecard.id == scorecard_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scorecard not found")
    db.delete(sc)
    db.commit()
    log_action(db=db, user=current_user, action="DELETE_SCORECARD", resource="scorecards", resource_id=scorecard_id,
               details=f"Deleted scorecard #{scorecard_id}",
               ip_address=request.client.host if request.client else None)
