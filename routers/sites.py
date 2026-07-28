from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.site import Site
from models.user import User
from schemas.site import SiteCreate, SiteOut
from services.audit_service import log_action
from services.auth_services import get_current_user, require_role

router = APIRouter(prefix="/sites", tags=["Sites"])


@router.get("/", response_model=List[SiteOut])
def get_all_sites(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all sites or restrict to assigned site for site managers."""
    if current_user.role == "site_manager":
        return db.query(Site).filter(Site.id == current_user.site_id).all()
    return db.query(Site).order_by(Site.name).all()


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == "site_manager" and current_user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Access denied")

    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.post("/", response_model=SiteOut, status_code=201)
def create_site(
    request: Request,
    payload: SiteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    existing = db.query(Site).filter(Site.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Site with this name already exists")

    site = Site(**payload.model_dump())
    db.add(site)
    db.commit()
    db.refresh(site)

    log_action(
        db=db,
        user=current_user,
        action="CREATE_SITE",
        resource="sites",
        resource_id=site.id,
        details=f"Created site: {site.name}",
        ip_address=request.client.host,
    )
    return site


@router.put("/{site_id}", response_model=SiteOut)
def update_site(
    request: Request,
    site_id: int,
    payload: SiteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    for key, val in payload.model_dump().items():
        setattr(site, key, val)

    db.commit()
    db.refresh(site)

    log_action(
        db=db,
        user=current_user,
        action="UPDATE_SITE",
        resource="sites",
        resource_id=site.id,
        details=f"Updated site #{site.id}: {site.name}",
        ip_address=request.client.host,
    )
    return site