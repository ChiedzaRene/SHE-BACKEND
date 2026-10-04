"""Deleting users who have records, and the audit log PDF export."""
from datetime import datetime

import pytest

from database import SessionLocal
from models.app_setting import AppSetting
from models.audit_log import AuditLog
from models.incident import Incident
from models.user import User
from services.auth_services import hash_password
from services.reports import AUDIT_EXPORT_MAX_ROWS, audit_log_document


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    db = SessionLocal()
    db.query(Incident).filter(Incident.description.like("del-test%")).delete(synchronize_session=False)
    db.query(User).filter(User.email.like("deltest-%")).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.details.like("%<b>pdf-markup%")).delete(synchronize_session=False)
    db.query(AppSetting).delete()
    db.commit()
    db.close()


def make_user(email, role="she_team"):
    db = SessionLocal()
    db.add(User(email=email, password=hash_password("password123"), role=role))
    db.commit()
    uid = db.query(User).filter(User.email == email).one().id
    db.close()
    return uid


def exists(uid):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.id == uid).first() is not None
    finally:
        db.close()


# ─── Delete ─────────────────────────────────────────────────────────────────

def test_delete_a_user_with_no_records_works_and_is_audited(client, auth):
    uid = make_user("deltest-clean@x.com")
    assert client.delete(f"/users/{uid}", headers=auth["admin"]).status_code == 200
    assert not exists(uid)
    db = SessionLocal()
    assert db.query(AuditLog).filter(AuditLog.action == "DELETE_USER", AuditLog.resource_id == uid).count() == 1
    db.close()


def test_delete_a_user_with_records_explains_and_keeps_the_account(client, auth):
    uid = make_user("deltest-busy@x.com", "site_manager")
    db = SessionLocal()
    for n in range(3):
        db.add(Incident(site_id=1, user_id=uid, type="injury", description=f"del-test {n}", severity="low"))
    db.commit()
    db.close()

    r = client.delete(f"/users/{uid}", headers=auth["admin"])
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "deltest-busy@x.com" in detail and "3 incidents" in detail and "Deactivate" in detail
    assert exists(uid)                                                    # nothing was deleted

    # The suggested alternative works: deactivating keeps the records and blocks sign-in
    assert client.put(f"/users/{uid}", json={"is_active": False}, headers=auth["admin"]).status_code == 200
    from services.auth_services import issue_token
    db = SessionLocal()
    token = issue_token(db.query(User).filter(User.id == uid).one())
    db.close()
    assert client.get("/sites/", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    db = SessionLocal()
    assert db.query(Incident).filter(Incident.user_id == uid).count() == 3
    db.close()


def test_singular_wording(client, auth):
    uid = make_user("deltest-one@x.com")
    db = SessionLocal()
    db.add(Incident(site_id=1, user_id=uid, type="spill", description="del-test one", severity="low"))
    db.commit()
    db.close()
    assert "recorded 1 incident." in client.delete(f"/users/{uid}", headers=auth["admin"]).json()["detail"]


def test_a_user_who_only_changed_a_setting_can_still_be_deleted(client, auth):
    uid = make_user("deltest-settings@x.com", "admin")
    db = SessionLocal()
    db.add(AppSetting(key="trir_limit", value="2.0", updated_by=uid))
    db.commit()
    db.close()
    assert client.delete(f"/users/{uid}", headers=auth["super"]).status_code == 200
    db = SessionLocal()
    assert db.query(AppSetting).filter(AppSetting.key == "trir_limit").one().updated_by is None
    db.close()


def test_who_may_delete_whom(client, auth):
    uid = make_user("deltest-rules@x.com")
    assert client.delete(f"/users/{uid}", headers=auth["she"]).status_code == 403
    assert client.delete(f"/users/{uid}", headers=auth["mgr"]).status_code == 403
    assert client.delete(f"/users/{uid}").status_code == 401
    sup_id = make_user("deltest-sup@x.com", "super_admin")
    assert client.delete(f"/users/{sup_id}", headers=auth["admin"]).status_code == 403     # admin can't delete a super admin
    assert client.delete(f"/users/{sup_id}", headers=auth["super"]).status_code == 200     # a super admin can
    assert client.delete(f"/users/{uid}", headers=auth["admin"]).status_code == 200


# ─── Audit log PDF ──────────────────────────────────────────────────────────

def test_audit_pdf_is_super_admin_only(client, auth):
    assert client.get("/audit-logs/export").status_code == 401
    for who in ("admin", "she", "mgr"):
        assert client.get("/audit-logs/export", headers=auth[who]).status_code == 403


def test_audit_pdf_downloads_and_is_itself_logged(client, auth):
    db = SessionLocal()
    before = db.query(AuditLog).filter(AuditLog.action == "EXPORT_AUDIT_LOG").count()
    db.close()
    r = client.get("/audit-logs/export", headers=auth["super"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and len(r.content) > 1500
    assert 'attachment; filename="she-audit-log-' in r.headers["content-disposition"]
    db = SessionLocal()
    entries = db.query(AuditLog).filter(AuditLog.action == "EXPORT_AUDIT_LOG").all()
    db.close()
    assert len(entries) == before + 1 and entries[-1].user_email == "super@x.com"


def test_audit_pdf_uses_the_same_filters_and_validates_them(client, auth):
    sup = auth["super"]
    ok = client.get("/audit-logs/export?action=DELETE_USER&start=2000-01-01", headers=sup)
    assert ok.status_code == 200 and ok.content.startswith(b"%PDF")
    assert client.get("/audit-logs/export?start=not-a-date", headers=sup).status_code == 422
    db = SessionLocal()
    last = db.query(AuditLog).filter(AuditLog.action == "EXPORT_AUDIT_LOG").order_by(AuditLog.id.desc()).first()
    db.close()
    assert "action DELETE_USER" in last.details and "from 2000-01-01" in last.details


def test_pdf_survives_markup_in_log_details(client, auth):
    db = SessionLocal()
    db.add(AuditLog(user_email="x@x.com", user_role="admin", action="TEST", resource="t",
                    details="<b>pdf-markup unclosed <i>& <para> tags", ip_address="1.2.3.4"))
    db.commit()
    db.close()
    r = client.get("/audit-logs/export?action=TEST", headers=auth["super"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_document_content_and_truncation():
    class E:  # just the fields the export reads
        def __init__(self, i):
            self.timestamp, self.user_email, self.user_role = datetime(2026, 10, 4, 12, 0, i % 60), f"u{i % 3}@x.com", "super_admin"
            self.action, self.resource, self.resource_id = "UPDATE_SITE", "sites", i
            self.details, self.ip_address = f"entry {i}", "10.0.0.1"

    entries = [E(i) for i in range(5)]
    doc = audit_log_document(entries, 5, "action UPDATE_SITE")
    assert doc["subtitle"] == "action UPDATE_SITE"
    assert doc["tables"][0]["columns"][0] == "When (UTC)"
    assert doc["tables"][0]["rows"][0][:5] == ["2026-10-04 12:00:00", "u0@x.com", "super admin", "UPDATE_SITE", "sites #0"]
    assert {k["label"]: k["value"] for k in doc["kpis"]}["People involved"] == "3"
    assert not any("most recent" in n for n in doc["notes"])

    capped = audit_log_document(entries, AUDIT_EXPORT_MAX_ROWS + 500, "")
    assert any("most recent" in n and "narrow the filters" in n for n in capped["notes"])
    empty = audit_log_document([], 0, "")
    assert empty["subtitle"] == "All activity" and empty["tables"][0]["rows"] == []
