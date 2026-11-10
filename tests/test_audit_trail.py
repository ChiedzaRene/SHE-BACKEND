"""The audit trail records every change: who made it, from where, and each field's old and new value."""
import json

from database import SessionLocal
from models.audit_log import AuditLog
from models.site import Site
from models.user import User
from services import audit_trail


def _latest(**filters):
    db = SessionLocal()
    try:
        q = db.query(AuditLog)
        for k, v in filters.items():
            q = q.filter(getattr(AuditLog, k) == v)
        return q.order_by(AuditLog.id.desc()).first()
    finally:
        db.close()


def test_a_named_entry_carries_exactly_what_changed(client, auth):
    db = SessionLocal()
    db.query(Site).filter(Site.id == 2).update({Site.region: "Bulawayo"})
    db.commit()
    db.close()
    r = client.put("/sites/2/region", json={"region": "Midlands"}, headers=auth["admin"])
    assert r.status_code == 200, r.text
    entry = _latest(action="UPDATE_SITE", resource="sites", resource_id=2)
    assert entry.user_email == "admin@x.com" and entry.user_role == "admin"
    assert entry.ip_address == "testclient"
    [change] = entry.changes
    assert change["op"] == "RECORD_UPDATED" and change["table"] == "sites" and change["id"] == 2
    assert change["fields"]["region"] == {"old": "Bulawayo", "new": "Midlands"}
    # one entry for the change, not a second automatic one as well
    assert _latest(resource="sites", resource_id=2).action == "UPDATE_SITE"

    # the list shows it, with plain names, to admins
    rows = client.get("/audit-logs/", params={"resource": "sites", "limit": 5}, headers=auth["admin"]).json()
    shown = next(x for x in rows if x["id"] == entry.id)
    assert shown["changes"][0]["fields"]["region"]["new"] == "Midlands"
    assert shown["changes"][0]["table_label"] == "Sites"


def test_a_change_nothing_else_describes_is_still_recorded(client, auth):
    """Adding a file to a fire inspection writes no named entry; the trail records it anyway."""
    sent = client.post("/fire-inspections/", data={
        "kind": "service_refill", "inspection_date": "2020-01-01", "inspector_name": "Tendai Moyo"},  # old: never the latest
        files=[("files", ("cert.pdf", b"%PDF-1.4 x", "application/pdf"))], headers=auth["mgr"])
    assert sent.status_code == 201, sent.text
    insp = sent.json()["id"]
    created = _latest(action="CREATE_FIRE_INSPECTION", resource_id=insp)
    tables = {c["table"] for c in created.changes}
    assert {"fire_inspections", "fire_inspection_files"} <= tables          # the files belong to it
    files = next(c for c in created.changes if c["table"] == "fire_inspection_files")
    assert files["fields"]["filename"]["new"] == "cert.pdf"
    assert files["fields"]["data"]["new"] == "(file, 10 bytes)"             # its size, never its contents

    more = client.post(f"/fire-inspections/{insp}/files", files={"file": ("tags.png", b"\x89PNG", "image/png")},
                       headers=auth["mgr"])
    assert more.status_code == 201, more.text
    entry = _latest(action="RECORD_CREATED", resource="fire_inspection_files")
    assert entry.user_email == "mgr@x.com"
    assert entry.changes[0]["fields"]["filename"]["new"] == "tags.png"
    assert entry.changes[0]["fields"]["inspection_id"] == {"old": None, "new": insp, "ref": "fire_inspections"}


def test_passwords_are_never_stored_in_the_trail(client, auth):
    db = SessionLocal()
    uid = db.query(User.id).filter(User.email == "she@x.com").scalar()
    db.close()
    r = client.put(f"/users/{uid}", json={"password": "Reset-by-admin-9"}, headers=auth["admin"])
    assert r.status_code == 200, r.text
    db = SessionLocal()
    rows = db.query(AuditLog).filter(AuditLog.resource == "users", AuditLog.resource_id == uid).all()
    hashed = db.query(User.password).filter(User.id == uid).scalar()
    db.close()
    dumped = json.dumps([r.changes for r in rows]) + " ".join(r.details or "" for r in rows)
    assert "Reset-by-admin-9" not in dumped and hashed not in dumped
    assert any((r.changes or [{}])[0].get("fields", {}).get("password") == {"old": None, "new": "(changed)"}
               for r in rows)
    # put the shared test account back as it was
    from services.auth_services import hash_password
    from tests.conftest import PASSWORD
    db = SessionLocal()
    db.query(User).filter(User.id == uid).update({User.password: hash_password(PASSWORD),
                                                  User.must_change_password: False, User.token_version: 0})
    db.commit()
    db.close()


def test_a_change_that_was_rolled_back_is_not_recorded():
    token = audit_trail.begin("10.0.0.1")
    db = SessionLocal()
    try:
        site = db.query(Site).first()
        site.region = "Nowhere"
        db.flush()
        db.rollback()                                 # never saved
        site = db.query(Site).first()
        site.name = site.name                         # no real change
        db.commit()
    finally:
        db.close()
    assert audit_trail.end(token) is None


def test_admins_and_super_admins_only(client, auth):
    for who in ("she", "mgr"):
        assert client.get("/audit-logs/", headers=auth[who]).status_code == 403
    assert client.get("/audit-logs/", headers=auth["admin"]).status_code == 200
