from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
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
def get_site(site_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


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