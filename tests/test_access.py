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


def test_legal_compliance_scorecard_and_records_are_gone(client, auth):
    # the Legal page is the licence register now; the old scorecard and legal records can't be used
    for path in ("/scorecard/", "/scorecard/site/1/latest", "/legal/"):
        assert client.get(path, headers=auth["admin"]).status_code == 404
    assert client.post("/scorecard/", json={"site_id": 1, "items": ITEMS}, headers=auth["mgr"]).status_code in (404, 405)


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


def test_operations_and_directors_can_read_everything_but_change_nothing(client, auth):
    from database import SessionLocal
    from models.user import User
    from services.auth_services import hash_password
    db = SessionLocal()
    for uid, email, role in ((150, "ops@x.com", "operations"), (151, "director@x.com", "director")):
        if not db.query(User).filter(User.id == uid).first():
            db.add(User(id=uid, email=email, password=hash_password("password123"), role=role))
    db.commit()
    db.close()
    for email in ("ops@x.com", "director@x.com"):
        h = {"Authorization": "Bearer " + client.post("/auth/login", data={"username": email, "password": "password123"}).json()["access_token"]}
        assert client.get("/incidents/", headers=h).status_code == 200
        assert client.get("/dashboard/summary", headers=h).status_code == 200
        assert len(client.get("/sites/", headers=h).json()) >= 2                 # every site
        blocked = client.post("/incidents/", json={"site_id": 1, "type": "spill", "description": "A small spill",
                                                    "severity": "low"}, headers=h)
        assert blocked.status_code == 403 and "view records" in blocked.json()["detail"]
        assert client.put("/incidents/1", json={"resolved": True}, headers=h).status_code == 403
        assert client.post("/notifications/read", json={"all": True}, headers=h).status_code == 200   # their own
        assert client.patch("/users/me", json={"full_name": "Reader"}, headers=h).status_code == 200
    created = client.post("/users", json={"email": "newdir@x.com", "password": "password123", "role": "director"},
                          headers=auth["admin"])
    assert created.status_code == 200 and created.json()["role"] == "director"


def test_incident_description_is_fixed_and_the_action_plan_is_separate(client, auth):
    # the action plan is the SHE team's (it comes with the corrective actions), not the site's
    refused = client.post("/incidents/", json={"site_id": 1, "type": "spill", "description": "Diesel spill at pump 2",
                                               "severity": "low", "action_plan": "Absorb and dispose"}, headers=auth["mgr"])
    assert refused.status_code == 403
    r = client.post("/incidents/", json={"site_id": 1, "type": "spill", "description": "Diesel spill at pump 2",
                                         "severity": "low"}, headers=auth["mgr"])
    assert r.status_code in (200, 201), r.text
    inc = r.json()
    changed = client.put(f"/incidents/{inc['id']}", json={"description": "Something else"}, headers=auth["she"])
    assert changed.status_code == 409 and "can't be changed" in changed.json()["detail"]
    assert client.put(f"/incidents/{inc['id']}", json={"action_plan": "Absorb"}, headers=auth["mgr"]).status_code == 403
    ok = client.put(f"/incidents/{inc['id']}", json={"description": "Diesel spill at pump 2",
                                                     "action_plan": "Absorb, dispose and retrain the attendant"},
                    headers=auth["she"])
    assert ok.status_code == 200 and ok.json()["description"] == "Diesel spill at pump 2"
    assert ok.json()["action_plan"] == "Absorb, dispose and retrain the attendant"
    # leave the shared test data as it was (other tests count site 1's incidents)
    from database import SessionLocal
    from models.incident import Incident
    db = SessionLocal()
    db.query(Incident).filter(Incident.id == inc["id"]).delete()
    db.commit()
    db.close()
