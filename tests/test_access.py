"""Authorization and access-control regression tests."""
NEW_SUPER = {"email": "new@x.com", "password": "password123", "role": "super_admin"}
ITEMS = [{"requirement_ref": "FWA-1", "score": 4}]


def test_register_requires_login(client):
    assert client.post("/auth/register", json=NEW_SUPER).status_code == 401


def test_admin_cannot_create_super_admin(client, auth):
    assert client.post("/auth/register", json=NEW_SUPER, headers=auth["admin"]).status_code == 403
    assert client.post("/users/", json=NEW_SUPER, headers=auth["admin"]).status_code == 403


def test_super_admin_can_create_super_admin(client, auth):
    r = client.post("/auth/register", json={**NEW_SUPER, "email": "ok@x.com"}, headers=auth["super"])
    assert r.status_code == 200


def test_admin_cannot_demote_or_delete_super_admin(client, auth):
    assert client.put("/users/1", json={"role": "site_manager"}, headers=auth["admin"]).status_code == 403
    assert client.delete("/users/1", headers=auth["admin"]).status_code == 403


def test_scorecard_requires_login(client):
    assert client.get("/scorecard/").status_code == 401
    assert client.post("/scorecard/", json={"site_id": 1, "items": ITEMS}).status_code == 401
    assert client.delete("/scorecard/1").status_code == 401


def test_site_manager_scorecard_scoping(client, auth):
    mgr = auth["mgr"]
    assert client.post("/scorecard/", json={"site_id": 1, "items": ITEMS}, headers=mgr).status_code == 201
    assert client.post("/scorecard/", json={"site_id": 2, "items": ITEMS}, headers=mgr).status_code == 403
    assert client.get("/scorecard/site/1/latest", headers=mgr).status_code == 200
    assert client.get("/scorecard/site/2/latest", headers=mgr).status_code == 403
    assert client.get("/scorecard/", headers=mgr).status_code == 200
    assert client.delete("/scorecard/1", headers=mgr).status_code == 403


def test_site_manager_cannot_read_other_site_incident_metrics(client, auth):
    assert client.get("/incidents/metrics/2", headers=auth["mgr"]).status_code == 403
    assert client.get("/incidents/metrics/1", headers=auth["mgr"]).status_code == 200


def test_inspection_upload_rules(client, auth):
    mgr = auth["mgr"]
    base = {"site_id": 1, "inspection_date": "2026-01-01"}
    html = {"file": ("a.html", b"<script>", "text/html")}
    png = {"file": ("a.png", b"x", "image/png")}
    assert client.post("/inspections/", data=base, files=html, headers=mgr).status_code == 400
    assert client.post("/inspections/", data=base, files=png, headers=mgr).status_code == 200
    assert client.post("/inspections/", data={**base, "site_id": 2}, headers=mgr).status_code == 403


def test_super_admin_can_change_password(client, auth):
    # A throwaway user: resetting a password signs that user out, which would break the shared admin token
    from database import SessionLocal
    from models.user import User
    from services.auth_services import hash_password
    db = SessionLocal()
    db.add(User(email="pw-throwaway@x.com", password=hash_password("old-password-1"), role="she_team"))
    db.commit()
    uid = db.query(User).filter(User.email == "pw-throwaway@x.com").one().id
    db.close()
    r = client.patch(f"/admin/users/{uid}", json={"password": "newpassword123"}, headers=auth["super"])
    assert r.status_code == 200
    db = SessionLocal()
    db.query(User).filter(User.id == uid).delete()
    db.commit()
    db.close()
