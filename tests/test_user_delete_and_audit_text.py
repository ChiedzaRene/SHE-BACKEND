"""Deleting users who have records, and how audit log text and names are shown."""
import pytest

from database import SessionLocal
from models.app_setting import AppSetting
from models.audit_log import AuditLog
from models.incident import Incident
from models.user import User
from services.auth_services import hash_password


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


def test_every_action_the_code_writes_has_a_plain_english_name():
    """Guards against adding a new log_action(...) code and showing it to people as RAW_CODE."""
    import pathlib
    import re
    from services.audit_labels import ACTION_LABELS, RESOURCE_LABELS
    root = pathlib.Path(__file__).resolve().parent.parent
    code = "\n".join(p.read_text() for d in ("routers", "services") for p in (root / d).glob("*.py"))
    actions = set(re.findall(r'action="([A-Z_]+)"', code))
    resources = set(re.findall(r'resource="([a-z_]+)"', code))
    assert actions - set(ACTION_LABELS) == set(), f"add labels for {actions - set(ACTION_LABELS)}"
    assert resources - set(RESOURCE_LABELS) == set(), f"add labels for {resources - set(RESOURCE_LABELS)}"


def test_audit_log_text_is_plain_not_double_encoded(client, auth):
    db = SessionLocal()
    db.add(AuditLog(user_email="enc@x.com", user_role="admin", action="TEST_ENC", resource="t",
                    details="TRIR limit 1.5 -> 2 & Pump <3> <script>alert(1)</script>ok", ip_address="1.1.1.1"))
    db.commit()
    db.close()
    row = client.get("/audit-logs/?action=TEST_ENC", headers=auth["super"]).json()[0]
    d = row["details"]
    assert d.startswith("TRIR limit 1.5 -> 2 & Pump")          # arrow and ampersand come back as typed
    assert "&gt;" not in d and "&amp;" not in d and "&lt;" not in d
    assert "<script" not in d and "</script" not in d           # tags are still stripped
    db = SessionLocal()
    db.query(AuditLog).filter(AuditLog.action == "TEST_ENC").delete()
    db.commit()
    db.close()
