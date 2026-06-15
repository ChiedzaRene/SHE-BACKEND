from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from database import get_db
from models.scorecard import ScorecardSubmission, ScorecardItem
from models.user import User
from models.site import Site
from schemas.scorecard import (
    ScorecardSubmissionCreate,
    ScorecardSubmissionResponse,
    ScorecardSummaryResponse,
)
from services.auth_services import get_current_user, require_role
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/scorecard", tags=["Scorecard"])


def _overall_percent(score: float) -> int:
    return round((score / 5) * 100)


# ---------------------------------------------------------------------------
# CREATE a new scorecard submission
# - site_manager: can only submit for their own site
# - admin / she_team: can submit for any site
# ---------------------------------------------------------------------------
@router.post("/", response_model=ScorecardSubmissionResponse)
def create_scorecard_submission(
    payload: ScorecardSubmissionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and current_user.site_id != payload.site_id:
        raise HTTPException(
            status_code=403,
            detail="Site managers can only submit scorecards for their own site",
        )

    if current_user.role not in ("site_manager", "admin", "she_team"):
        raise HTTPException(status_code=403, detail="Not permitted to submit scorecards")

    site = db.query(Site).filter(Site.id == payload.site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    overall_score = sum(item.score for item in payload.items) / len(payload.items)
    overall_score = round(overall_score, 2)

    submission = ScorecardSubmission(
        site_id=payload.site_id,
        submitted_by=current_user.id,
        overall_score=overall_score,
    )
    db.add(submission)
    db.flush()  # get submission.id before adding items

    for item in payload.items:
        db.add(
            ScorecardItem(
                submission_id=submission.id,
                requirement_id=item.requirement_id,
                requirement_title=item.requirement_title,
                score=item.score,
            )
        )

    db.commit()
    db.refresh(submission)
    return submission


# ---------------------------------------------------------------------------
# LIST latest scores across all sites (admin / she_team)
# Filterable by site_id, min/max overall score, date range
# Returns the latest submission per site
# ---------------------------------------------------------------------------
@router.get("/", response_model=List[ScorecardSummaryResponse])
def list_latest_scores(
    site_id: Optional[int] = Query(None, description="Filter by a specific site"),
    min_score: Optional[float] = Query(None, ge=0, le=5, description="Minimum overall score (0-5)"),
    max_score: Optional[float] = Query(None, ge=0, le=5, description="Maximum overall score (0-5)"),
    start_date: Optional[datetime] = Query(None, description="Only submissions on/after this date"),
    end_date: Optional[datetime] = Query(None, description="Only submissions on/before this date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "she_team")),
):
    # Subquery: latest submission id per site
    latest_ids_subq = (
        db.query(
            ScorecardSubmission.site_id,
            ScorecardSubmission.id,
        )
        .order_by(ScorecardSubmission.site_id, desc(ScorecardSubmission.submitted_at))
    )

    # Build a map of site_id -> latest submission id
    latest_per_site = {}
    for site_id_val, sub_id in latest_ids_subq:
        if site_id_val not in latest_per_site:
            latest_per_site[site_id_val] = sub_id

    latest_submission_ids = list(latest_per_site.values())
    if not latest_submission_ids:
        return []

    query = (
        db.query(ScorecardSubmission)
        .options(
            joinedload(ScorecardSubmission.site),
            joinedload(ScorecardSubmission.submitter),
        )
        .filter(ScorecardSubmission.id.in_(latest_submission_ids))
    )

    if site_id is not None:
        query = query.filter(ScorecardSubmission.site_id == site_id)
    if min_score is not None:
        query = query.filter(ScorecardSubmission.overall_score >= min_score)
    if max_score is not None:
        query = query.filter(ScorecardSubmission.overall_score <= max_score)
    if start_date is not None:
        query = query.filter(ScorecardSubmission.submitted_at >= start_date)
    if end_date is not None:
        query = query.filter(ScorecardSubmission.submitted_at <= end_date)

    submissions = query.order_by(desc(ScorecardSubmission.submitted_at)).all()

    return [
        ScorecardSummaryResponse(
            id=s.id,
            site_id=s.site_id,
            site_name=s.site.name if s.site else None,
            submitted_by=s.submitted_by,
            submitted_by_name=getattr(s.submitter, "name", None) or getattr(s.submitter, "username", None),
            overall_score=s.overall_score,
            overall_percent=_overall_percent(s.overall_score),
            submitted_at=s.submitted_at,
        )
        for s in submissions
    ]


# ---------------------------------------------------------------------------
# GET latest submission for a single site
# - site_manager: own site only
# - admin / she_team: any site
# ---------------------------------------------------------------------------
@router.get("/site/{site_id}/latest", response_model=ScorecardSubmissionResponse)
def get_latest_site_scorecard(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    submission = (
        db.query(ScorecardSubmission)
        .options(joinedload(ScorecardSubmission.items))
        .filter(ScorecardSubmission.site_id == site_id)
        .order_by(desc(ScorecardSubmission.submitted_at))
        .first()
    )

    if not submission:
        raise HTTPException(status_code=404, detail="No scorecard submissions found for this site")

    return submission


# ---------------------------------------------------------------------------
# GET full submission history for a single site
# - site_manager: own site only
# - admin / she_team: any site
# ---------------------------------------------------------------------------
@router.get("/site/{site_id}", response_model=List[ScorecardSubmissionResponse])
def get_site_scorecard_history(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    submissions = (
        db.query(ScorecardSubmission)
        .options(joinedload(ScorecardSubmission.items))
        .filter(ScorecardSubmission.site_id == site_id)
        .order_by(desc(ScorecardSubmission.submitted_at))
        .all()
    )

    return submissions


# ---------------------------------------------------------------------------
# GET a single submission by id
# - site_manager: only if it belongs to their site
# - admin / she_team: any
# ---------------------------------------------------------------------------
@router.get("/{submission_id}", response_model=ScorecardSubmissionResponse)
def get_scorecard_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    submission = (
        db.query(ScorecardSubmission)
        .options(joinedload(ScorecardSubmission.items))
        .filter(ScorecardSubmission.id == submission_id)
        .first()
    )

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    if current_user.role == "site_manager" and current_user.site_id != submission.site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return submission