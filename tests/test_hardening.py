"""Site delete, authenticated uploads, headers, docs, pagination and incident dates."""
import re
from datetime import date, datetime, timedelta

from database import SessionLocal
from models.site import Site

def _delete_incidents(*ids):
    """The metrics tests assert exact counts, so tests here must not leave incidents behind."""
    from models.incident import Incident
    db = SessionLocal()
    db.query(Incident).filter(Incident.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    db.close()


INCIDENT = {"site_id": 1, "type": "injury", "description": "slipped on forecourt", "severity": "low"}


def test_security_headers_and_docs_off_by_default(client):
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_incident_occurred_at(client, auth):
    mgr = auth["mgr"]
    future = (datetime.utcnow() + timedelta(days=30)).isoformat()
    assert client.post("/incidents/", json={**INCIDENT, "occurred_at": future}, headers=mgr).status_code == 422
    past = (datetime.utcnow() - timedelta(days=3)).isoformat()
    r1 = client.post("/incidents/", json={**INCIDENT, "occurred_at": past}, headers=mgr)
    assert r1.status_code == 200 and r1.json()["occurred_at"].startswith(past[:10])
    # still optional
    r2 = client.post("/incidents/", json=INCIDENT, headers=mgr)
    assert r2.status_code == 200
    # site managers cannot log for another site
    assert client.post("/incidents/", json={**INCIDENT, "site_id": 2}, headers=mgr).status_code == 403
    _delete_incidents(r1.json()["id"], r2.json()["id"])


def test_pagination_is_optional_and_counts(client, auth):
    admin = auth["admin"]
    everything = client.get("/incidents/", headers=admin)
    assert "x-total-count" not in everything.headers  # unchanged behaviour without limit
    total = len(everything.json())
    page = client.get("/incidents/?limit=2&offset=1", headers=admin)
    assert page.status_code == 200
    assert len(page.json()) == 2
    assert page.headers["x-total-count"] == str(total)
    assert client.get("/incidents/?limit=0", headers=admin).status_code == 422
    assert client.get("/incidents/?limit=5000", headers=admin).status_code == 422
    # scoping still applies when paginated
    mgr_page = client.get("/incidents/?limit=100", headers=auth["mgr"])
    assert {i["site_id"] for i in mgr_page.json()} == {1}


def test_site_delete_rules(client, auth):
    db = SessionLocal()
    db.add(Site(id=50, name="Empty Site", address="e"))
    db.commit()
    db.close()
    assert client.delete("/sites/50").status_code == 401
    assert client.delete("/sites/50", headers=auth["mgr"]).status_code == 403
    assert client.delete("/sites/50", headers=auth["she"]).status_code == 403
    assert client.delete("/sites/999", headers=auth["admin"]).status_code == 404
    busy = client.delete("/sites/1", headers=auth["admin"])
    assert busy.status_code == 409 and "incidents" in busy.json()["detail"]
    assert client.delete("/sites/50", headers=auth["admin"]).status_code == 200
    assert client.get("/sites/50", headers=auth["admin"]).status_code == 404


def test_uploads_require_login_and_site_access(client, auth):
    mgr = auth["mgr"]
    r = client.post(
        "/inspections/",
        data={"site_id": 1, "inspection_date": date.today().isoformat()},
        files={"file": ("evidence.png", b"\x89PNG-bytes", "image/png")},
        headers=mgr,
    )
    assert r.status_code == 200
    url = r.json()["file_url"]
    assert re.match(r"^/uploads/inspections/[0-9a-f-]{36}\.png$", url)

    assert client.get(url).status_code == 401  # no longer public
    assert client.get(url, headers=mgr).content == b"\x89PNG-bytes"
    assert client.get(url, headers=auth["admin"]).status_code == 200
    assert client.get("/uploads/inspections/../../she_system.db", headers=mgr).status_code == 404
    assert client.get("/uploads/inspections/not-a-real-file.png", headers=mgr).status_code == 404


def test_sites_without_site_manager_access_blocked_for_other_site_upload(client, auth):
    # A manager of site 2 cannot download site 1 evidence (create a site-2 manager on the fly)
    from models.user import User
    from services.auth_services import hash_password
    db = SessionLocal()
    db.add(User(id=60, email="mgr2@x.com", password=hash_password("password123"),
                role="site_manager", site_id=2))
    db.commit()
    db.close()
    from services.auth_services import create_access_token
    mgr2 = {"Authorization": "Bearer " + create_access_token({"sub": "mgr2@x.com"})}
    own = client.get("/inspections/", headers=auth["mgr"]).json()
    url = next(i["file_url"] for i in own if i["file_url"])
    assert client.get(url, headers=mgr2).status_code == 403
