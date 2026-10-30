from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db
from models.site import Site
from models.audit import Audit
from models.corrective_action import CorrectiveAction
from models.incident import Incident
from models.inspections import Inspection
from models.legal import Legal
from models.safety_talk import SafetyTalk
from models.site_inspection import SiteInspection
from models.site_licence import SiteLicence
from models.scorecard import Scorecard
from models.site_hours import SiteHours
from models.training import Training
from models.user import User
from pydantic import BaseModel, Field

from schemas.site import SiteCreate, SiteOut
from services.audit_service import log_action
from services.access import assert_site_access
from services.auth_services import get_current_user, require_role
from services.clock import local_today
from services.regions import REGIONS, canonical, choose_message

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


def _region(value, current=None):
    """A site's region must be one of the regions (or none); a region set before the list existed may stay."""
    if not value:
        return None
    if current and value == current:
        return value
    region = canonical(value)
    if not region:
        raise HTTPException(status_code=422, detail=choose_message())
    return region


@router.get("/regions")
def list_regions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every region with its regional manager(s) and how many sites are in it."""
    counts = {}
    for (region,) in db.query(Site.region).all():
        counts[region] = counts.get(region, 0) + 1
    managers = {}
    for u in db.query(User).filter(User.role == "regional_manager", User.is_active.is_(True)).order_by(User.full_name):
        managers.setdefault(u.region, []).append(u.full_name or u.email)
    # regions typed in before the fixed list stay visible until their sites are moved
    older = sorted(r for r in counts if r and r not in REGIONS)
    return {
        "regions": [{"name": r, "sites": counts.get(r, 0), "managers": managers.get(r, []), "current": r in REGIONS}
                    for r in REGIONS + older],
        "unallocated": counts.get(None, 0),
    }


class RegionChoice(BaseModel):
    region: Optional[str] = Field(default=None, max_length=100)


@router.put("/{site_id}/region", response_model=SiteOut)
def allocate_region(
    request: Request,
    site_id: int,
    payload: RegionChoice,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    """Move a site into a region (or take it out of one)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    before = site.region
    site.region = _region(payload.region, site.region)
    db.commit()
    db.refresh(site)
    log_action(db=db, user=current_user, action="UPDATE_SITE", resource="sites", resource_id=site.id,
               details=f"{site.name}: region {before or 'none'} -> {site.region or 'none'}",
               ip_address=request.client.host if request.client else None)
    return site


@router.get("/{site_id}", response_model=SiteOut)
def get_site(
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    assert_site_access(current_user, site_id)

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

    # weekly toolbox talks are due from the site's first Monday
    data = payload.model_dump()
    data["region"] = _region(data.get("region"))
    site = Site(**data, talks_from=local_today())
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

    data = payload.model_dump()
    data["region"] = _region(data.get("region"), site.region)
    for key, val in data.items():
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


@router.delete("/{site_id}")
def delete_site(
    request: Request,
    site_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "super_admin")),
):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Safety records must never be orphaned or silently deleted with their site
    linked = {
        "incidents": Incident,
        "audits": Audit,
        "legal records": Legal,
        "trainings": Training,
        "inspections": Inspection,
        "corrective actions": CorrectiveAction,
        "scorecards": Scorecard,
        "hours entries": SiteHours,
        "SHE talks": SafetyTalk,
        "inspection reports": SiteInspection,
        "licences": SiteLicence,
        "users": User,
    }
    in_use = [
        f"{count} {name}"
        for name, model in linked.items()
        if (count := db.query(model).filter(model.site_id == site_id).count())
    ]
    if in_use:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a site that still has " + ", ".join(in_use),
        )

    name = site.name
    db.delete(site)
    db.commit()
    log_action(
        db=db,
        user=current_user,
        action="DELETE_SITE",
        resource="sites",
        resource_id=site_id,
        details=f"Deleted site #{site_id}: {name}",
        ip_address=request.client.host if request.client else None,
    )
    return {"message": "Site deleted"}
