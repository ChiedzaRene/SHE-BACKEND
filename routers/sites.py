from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
<<<<<<< HEAD
from typing import List

from database import get_db
from models.site import Site
from schemas.site import SiteCreate, SiteOut

router = APIRouter(prefix="/sites", tags=["Sites"])


@router.get("/", response_model=List[SiteOut])
def get_all_sites(db: Session = Depends(get_db)):
    """Return all sites — used by the site filter dropdown in ScorecardOverview."""
    return db.query(Site).order_by(Site.name).all()


@router.get("/{site_id}", response_model=SiteOut)
=======
from database import get_db
from models.site import Site
from schemas.site import SiteCreate, SiteUpdate, SiteResponse
from typing import List

router = APIRouter(prefix="/sites", tags=["Sites"])

# Get all sites
@router.get("/", response_model=List[SiteResponse])
def get_all_sites(db: Session = Depends(get_db)):
    return db.query(Site).all()

# Get one site
@router.get("/{site_id}", response_model=SiteResponse)
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site

<<<<<<< HEAD

@router.post("/", response_model=SiteOut, status_code=201)
def create_site(payload: SiteCreate, db: Session = Depends(get_db)):
    existing = db.query(Site).filter(Site.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="Site with this name already exists")
    site = Site(**payload.model_dump())
    db.add(site)
    db.commit()
    db.refresh(site)
    return site


@router.put("/{site_id}", response_model=SiteOut)
def update_site(site_id: int, payload: SiteCreate, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    for key, val in payload.model_dump().items():
        setattr(site, key, val)
    db.commit()
    db.refresh(site)
    return site


@router.delete("/{site_id}", status_code=204)
def delete_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    db.delete(site)
    db.commit()
=======
# Create a site
@router.post("/", response_model=SiteResponse)
def create_site(site_data: SiteCreate, db: Session = Depends(get_db)):
    new_site = Site(**site_data.model_dump())
    db.add(new_site)
    db.commit()
    db.refresh(new_site)
    return new_site

# Update a site
@router.put("/{site_id}", response_model=SiteResponse)
def update_site(site_id: int, site_data: SiteUpdate, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    for key, value in site_data.model_dump(exclude_unset=True).items():
        setattr(site, key, value)
    db.commit()
    db.refresh(site)
    return site
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d
