"""SHE files: documents the SHE team or an admin shares with other roles.

The uploader chooses who the file is for (site managers, the SHE team, admins; site managers of
every site or of one site) and whether it is view only. A view-only file can be opened in the app
but its download link is refused for everyone except the person who uploaded it.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, undefer

from database import get_db
from models.she_file import SheFile
from models.site import Site
from models.user import User
from services.audit_service import log_action
from services.auth_services import OVERSIGHT_ROLES, get_current_user, require_role
from services.files import clean_filename, file_response, is_viewable, read_upload
from services.notifications import notify, short, site_name, who

router = APIRouter(prefix="/she-files", tags=["SHE files"])

AUDIENCES = ("site_manager", "she_team", "admin")
UPLOADER_ROLES = ("admin", "super_admin", "she_team")


class SheFileOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    filename: str
    content_type: str
    size: int
    view_only: bool
    audience: List[str]
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    uploaded_by: int
    uploaded_by_name: str
    created_at: Optional[datetime] = None
    can_view: bool          # can be opened inside the app (PDF or image)
    can_download: bool
    can_delete: bool


def _is_admin(user: User) -> bool:
    return user.role in ("admin", "super_admin")


def _audience(f: SheFile) -> List[str]:
    return [a for a in (f.audience or "").split(",") if a]


def _can_see(user: User, f: SheFile) -> bool:
    if f.uploaded_by == user.id or _is_admin(user) or user.role in OVERSIGHT_ROLES:
        return True  # admins, operations and directors oversee every shared file
    aud = _audience(f)
    if user.role == "she_team":
        return "she_team" in aud
    if user.role == "site_manager":
        return "site_manager" in aud and (f.site_id is None or f.site_id == user.site_id)
    return False


def _viewable(f: SheFile) -> bool:
    return is_viewable(f.filename)


def _can_download(user: User, f: SheFile) -> bool:
    return not f.view_only or f.uploaded_by == user.id


def _out(db: Session, user: User, f: SheFile, names: dict, sites: dict) -> SheFileOut:
    return SheFileOut(
        id=f.id, title=f.title, description=f.description, filename=f.filename, content_type=f.content_type,
        size=f.size, view_only=f.view_only, audience=_audience(f), site_id=f.site_id,
        site_name=sites.get(f.site_id) if f.site_id else None, uploaded_by=f.uploaded_by,
        uploaded_by_name=names.get(f.uploaded_by, "Someone"), created_at=f.created_at,
        can_view=_viewable(f), can_download=_can_download(user, f),
        can_delete=f.uploaded_by == user.id or _is_admin(user),
    )


def _get_visible(db: Session, user: User, file_id: int, with_data: bool = False) -> SheFile:
    query = db.query(SheFile)
    if with_data:
        query = query.options(undefer(SheFile.data))
    f = query.filter(SheFile.id == file_id).first()
    if not f or not _can_see(user, f):
        raise HTTPException(status_code=404, detail="File not found")
    return f


def _file_response(f: SheFile, kind: str) -> Response:
    return file_response(f.data, f.content_type, f.filename, kind)


@router.get("/", response_model=List[SheFileOut])
def list_files(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    files = [f for f in db.query(SheFile).order_by(SheFile.created_at.desc(), SheFile.id.desc()).all()
             if _can_see(current_user, f)]
    names = {u.id: (u.full_name or u.email) for u in
             db.query(User).filter(User.id.in_({f.uploaded_by for f in files} or {0})).all()}
    sites = {s.id: s.name for s in db.query(Site).all()}
    return [_out(db, current_user, f, names, sites) for f in files]


@router.post("/", response_model=SheFileOut, status_code=201)
async def upload_file(
    request: Request,
    title: str = Form(..., max_length=200),
    description: Optional[str] = Form(None, max_length=2000),
    audience: str = Form(..., description="comma-separated: site_manager, she_team, admin"),
    site_id: Optional[int] = Form(None),
    view_only: bool = Form(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(*UPLOADER_ROLES)),
):
    title = " ".join(title.split())
    if not title:
        raise HTTPException(status_code=422, detail="Give the file a title.")
    roles = sorted({a.strip() for a in audience.split(",") if a.strip()})
    if not roles or any(r not in AUDIENCES for r in roles):
        raise HTTPException(status_code=422, detail="Choose who the file is for: site managers, the SHE team and/or admins.")
    if site_id is not None:
        if "site_manager" not in roles:
            site_id = None  # a site only narrows down which site managers get it
        elif not db.query(Site.id).filter(Site.id == site_id).first():
            raise HTTPException(status_code=404, detail="Site not found")

    filename, content_type = clean_filename(file)
    if view_only and not is_viewable(filename):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files and images can be view only, because they open inside the app. "
                   "Save the document as a PDF first, or allow downloading.",
        )
    data = await read_upload(file)

    f = SheFile(
        title=title, description=(description or "").strip() or None, filename=filename,
        content_type=content_type, size=len(data), data=data, view_only=view_only,
        audience=",".join(roles), site_id=site_id, uploaded_by=current_user.id,
    )
    db.add(f)
    db.commit()
    db.refresh(f)

    where = f" ({site_name(db, site_id)})" if site_id else ""
    log_action(db=db, user=current_user, action="UPLOAD_SHE_FILE", resource="she_files", resource_id=f.id,
               details=f"Shared \"{short(title, 80)}\" ({filename}) with {', '.join(roles)}{where}"
                       + (", view only" if view_only else ""),
               ip_address=request.client.host if request.client else None)

    recipients = db.query(User).filter(User.is_active.is_(True)).all()
    notify(
        db, [u for u in recipients if u.id != current_user.id and _can_see(u, f) and (
            not _is_admin(u) or "admin" in roles)],
        kind="file_shared", title=f"New SHE file: {short(title, 150)}",
        message=f"{who(current_user)} shared {filename}" + (" (view only)" if view_only else ""),
        link="/she-files", resource="she_files", resource_id=f.id, actor=current_user,
    )
    names = {current_user.id: current_user.full_name or current_user.email}
    sites = {site_id: site_name(db, site_id)} if site_id else {}
    return _out(db, current_user, f, names, sites)


@router.get("/{file_id}/view")
def view_file(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The file's contents for showing inside the app (PDFs and images only)."""
    f = _get_visible(db, current_user, file_id, with_data=True)
    if not _viewable(f):
        raise HTTPException(status_code=415, detail="This type of file can't be shown in the app. Download it instead.")
    return _file_response(f, "inline")


@router.get("/{file_id}/download")
def download_file(
    request: Request, file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    f = _get_visible(db, current_user, file_id, with_data=True)
    if not _can_download(current_user, f):
        raise HTTPException(status_code=403, detail="This file is view only: the person who shared it hasn't allowed downloads.")
    log_action(db=db, user=current_user, action="DOWNLOAD_SHE_FILE", resource="she_files", resource_id=f.id,
               details=f"Downloaded \"{short(f.title, 80)}\" ({f.filename})",
               ip_address=request.client.host if request.client else None)
    return _file_response(f, "attachment")


@router.delete("/{file_id}")
def delete_file(
    request: Request, file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    f = _get_visible(db, current_user, file_id)
    if f.uploaded_by != current_user.id and not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Only the person who shared this file or an admin can delete it.")
    title, filename = f.title, f.filename
    db.delete(f)
    db.commit()
    log_action(db=db, user=current_user, action="DELETE_SHE_FILE", resource="she_files", resource_id=file_id,
               details=f"Deleted \"{short(title, 80)}\" ({filename})",
               ip_address=request.client.host if request.client else None)
    return {"message": "File deleted"}
