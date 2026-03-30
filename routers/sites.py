from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
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
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site

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