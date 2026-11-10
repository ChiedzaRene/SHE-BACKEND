"""The audit trail: every record created, changed or deleted, by whom, from where, and what changed.

How it works, per request:
  1. A middleware opens a trail for the request (who: set once the person is signed in; their IP address).
  2. After every database flush, each changed row is noted with its old and new values. The notes are only
     kept once the transaction commits; a rolled-back change was never made, so it is never recorded.
  3. When the code writes its own named entry (log_action, e.g. "Incident updated"), it takes the notes for
     that record and the records that belong to it, so the entry shows exactly what changed.
  4. At the end of the request, any change no named entry took is written as its own entry
     ("Record added / changed / deleted"), so nothing that changed goes unrecorded.

Passwords and file contents are never stored: a password change shows as "(changed)", a file as its size.
"""
import contextvars
import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

logger = logging.getLogger("she_portal")

_trail = contextvars.ContextVar("audit_trail", default=None)

# Tables whose rows are the trail itself, or automatic messages rather than records people change
SKIP_TABLES = {"audit_logs", "notifications"}
# Columns that change on their own as people use the portal: not worth a trail entry on their own
NOISE = {"last_active_at", "updated_at", "token_version", "reminded_at", "reminded_30", "reminded_90",
         "reminded_expired"}
SECRET = {"password"}
MAX_TEXT = 500

CREATED, UPDATED, DELETED = "RECORD_CREATED", "RECORD_UPDATED", "RECORD_DELETED"


# ---------------- the request's trail ----------------

def begin(ip: str = None):
    """Start the trail for one request; returns the token to end it with."""
    return _trail.set({"who": None, "ip": ip, "pending": []})


def end(token):
    """Close the request's trail; returns it if it still holds changes to write (see write_leftovers)."""
    trail = _trail.get()
    _trail.reset(token)
    return trail if trail and trail["pending"] else None


def set_actor(user) -> None:
    trail = _trail.get()
    if trail is not None and user is not None:
        trail["who"] = (user.email, user.role)


def current_ip():
    trail = _trail.get()
    return trail["ip"] if trail else None


# ---------------- noting changes ----------------

def _plain(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"(file, {len(bytes(value)):,} bytes)"
    if isinstance(value, (dict, list)):
        text = repr(value)
    else:
        text = str(value)
        if "<" in text and ">" in text:  # formatted text: keep the words, not the markup
            from services.richtext import as_text
            text = as_text(text)
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"


def _refs(mapper) -> dict:
    """column -> the table it points at (e.g. site_id -> sites), so names can be shown instead of numbers."""
    out = {}
    for col in mapper.local_table.columns:
        for fk in col.foreign_keys:
            out[col.key] = fk.column.table.name
    return out


def _note(obj, op: str):
    insp = inspect(obj)
    mapper = insp.mapper
    table = mapper.local_table.name
    if table in SKIP_TABLES:
        return None
    refs = _refs(mapper)
    fields = {}
    for attr in mapper.column_attrs:
        key = attr.key
        if key in NOISE:
            continue
        hist = insp.attrs[key].history
        if op == UPDATED:
            if not hist.has_changes():
                continue
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if old == new:
                continue
        else:
            if key not in insp.dict:  # not loaded (e.g. a file's contents): leave it out
                continue
            value = insp.dict.get(key)
            if value is None or value == "" or (op == DELETED and key == "id"):
                continue
            old, new = (value, None) if op == DELETED else (None, value)
        if key in SECRET:
            fields[key] = {"old": None, "new": "(changed)" if op == UPDATED else "(set)"}
            continue
        change = {"old": _plain(old), "new": _plain(new)}
        if key in refs:
            change["ref"] = refs[key]
        fields[key] = change
    if op == UPDATED and not fields:
        return None
    keys = mapper.primary_key
    pk = insp.dict.get(keys[0].key) if len(keys) == 1 else None  # new rows have their id by now, not yet an identity
    parents = {}
    for key, target in refs.items():  # the records this one belongs to (an incident's investigation, files...)
        value = insp.dict.get(key)
        if value is not None:
            parents.setdefault(target, set()).add(value)
    return {"op": op, "table": table, "id": pk if isinstance(pk, int) else None, "fields": fields, "parents": parents}


def _after_flush(session, flush_context):
    if _trail.get() is None:
        return  # not inside a request (start-up, scheduled jobs, scripts)
    notes = session.info.setdefault("audit_notes", [])
    for op, objs in ((CREATED, session.new), (UPDATED, session.dirty), (DELETED, session.deleted)):
        for obj in objs:
            if op == UPDATED and not session.is_modified(obj, include_collections=False):
                continue
            try:
                note = _note(obj, op)
            except Exception:  # noqa: BLE001  never let the trail stop a save
                logger.exception("Could not note an audit change")
                note = None
            if note:
                notes.append(note)


def _after_commit(session):
    notes = session.info.pop("audit_notes", None)
    trail = _trail.get()
    if notes and trail is not None:
        trail["pending"].extend(notes)


def _after_rollback(session):
    session.info.pop("audit_notes", None)  # never made, so never recorded


event.listen(Session, "after_flush", _after_flush)
event.listen(Session, "after_commit", _after_commit)
event.listen(Session, "after_soft_rollback", lambda session, previous: _after_rollback(session))


# ---------------- writing entries ----------------

def _belongs(note: dict, resource: str, resource_id) -> bool:
    if resource_id is None:
        return note["table"] == resource and note["id"] is None
    if note["table"] == resource and note["id"] == resource_id:
        return True
    return resource_id in note["parents"].get(resource, set())


def _public(note: dict) -> dict:
    return {"op": note["op"], "table": note["table"], "id": note["id"], "fields": note["fields"]}


def claim(session, resource: str, resource_id) -> list:
    """The noted changes to this record (and the records that belong to it), taken off the trail."""
    trail = _trail.get()
    pools = [session.info.get("audit_notes") or []]
    if trail is not None:
        pools.append(trail["pending"])
    taken = []
    for pool in pools:
        keep = []
        for note in pool:
            (taken if _belongs(note, resource, resource_id) else keep).append(note)
        pool[:] = keep
    return [_public(n) for n in taken]


def describe(changes: list) -> str:
    """One line a person can read: 'status: open → closed; due date: 1 Nov → 8 Nov'."""
    parts = []
    for c in changes:
        for key, v in c["fields"].items():
            name = key.replace("_", " ")
            if c["op"] == UPDATED:
                parts.append(f"{name}: {v['old'] if v['old'] not in (None, '') else '(empty)'} → "
                             f"{v['new'] if v['new'] not in (None, '') else '(empty)'}")
        if c["op"] != UPDATED:
            parts.append(f"{'added' if c['op'] == CREATED else 'deleted'} {c['table'].replace('_', ' ')} #{c['id']}")
    text = "; ".join(parts)
    return text if len(text) <= 1000 else text[:999] + "…"


def write_leftovers(trail: dict) -> None:
    from database import SessionLocal
    from models.audit_log import AuditLog

    email, role = trail["who"] or ("(not signed in)", "unknown")
    db = SessionLocal()
    try:
        for note in trail["pending"]:
            change = _public(note)
            db.add(AuditLog(user_email=email, user_role=role, action=note["op"], resource=note["table"],
                            resource_id=note["id"], details=describe([change]), changes=[change],
                            ip_address=trail["ip"]))
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("Could not write the audit trail")
    finally:
        db.close()
