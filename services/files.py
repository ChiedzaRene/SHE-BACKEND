"""Uploaded documents kept in the database: which types are accepted, and how they are served back.

Files live in the database rather than on the server's disk, which Render wipes on every deploy.
"""
import os
from typing import Tuple
from urllib.parse import quote

from fastapi import HTTPException, Response, UploadFile

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB

# Allow-list, with the type we serve each one as (never the type the browser claimed: an .html or .svg
# file served from our origin could run script). `True` = can be shown inside the app.
FILE_TYPES = {
    ".pdf": ("application/pdf", True),
    ".png": ("image/png", True),
    ".jpg": ("image/jpeg", True),
    ".jpeg": ("image/jpeg", True),
    ".gif": ("image/gif", True),
    ".webp": ("image/webp", True),
    ".txt": ("text/plain; charset=utf-8", False),
    ".csv": ("text/csv; charset=utf-8", False),
    ".doc": ("application/msword", False),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", False),
    ".xls": ("application/vnd.ms-excel", False),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", False),
    ".ppt": ("application/vnd.ms-powerpoint", False),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", False),
}
ALLOWED_LIST = "PDF, images (PNG, JPG, GIF, WebP), Word, Excel, PowerPoint, CSV and text files"


def is_viewable(filename: str) -> bool:
    """PDFs and images can be shown inside the app."""
    return FILE_TYPES.get(os.path.splitext(filename or "")[1].lower(), ("", False))[1]


def clean_filename(upload: UploadFile) -> Tuple[str, str]:
    """The upload's bare file name and the content type we will serve it as; refuses other types."""
    filename = os.path.basename((upload.filename or "").replace("\\", "/")).strip()
    ext = os.path.splitext(filename)[1].lower()
    if not filename or ext not in FILE_TYPES:
        raise HTTPException(status_code=400, detail=f"That type of file can't be uploaded. Allowed: {ALLOWED_LIST}.")
    return filename[:255], FILE_TYPES[ext][0]


async def read_upload(upload: UploadFile) -> bytes:
    data = await upload.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="The file is too large (the limit is 10 MB).")
    if not data:
        raise HTTPException(status_code=400, detail="The file is empty.")
    return data


def _disposition(kind: str, filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def file_response(data: bytes, content_type: str, filename: str, kind: str = "attachment") -> Response:
    """kind: "inline" to show in the app, "attachment" to download."""
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": _disposition(kind, filename),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            # if the file is ever opened directly, nothing in it may run
            "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
        },
    )
