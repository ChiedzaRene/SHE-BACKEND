import os
import sys
import tempfile

# Must be set before the app is imported: it reads these at import time.
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-characters"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(_tmp)  # uploads/ is created relative to the working directory

import pytest
from fastapi.testclient import TestClient

import main
from database import SessionLocal
from models.incident import Incident
from models.site import Site
from models.user import User
from services.auth_services import hash_password

PASSWORD = "password123"


@pytest.fixture(scope="session")
def client():
    db = SessionLocal()
    db.add_all([Site(id=1, name="Site A", address="a"), Site(id=2, name="Site B", address="b")])
    db.add_all([
        User(id=1, email="super@x.com", password=hash_password(PASSWORD), role="super_admin"),
        User(id=2, email="admin@x.com", password=hash_password(PASSWORD), role="admin"),
        User(id=3, email="mgr@x.com", password=hash_password(PASSWORD), role="site_manager",
             site_id=1, full_name="Manager"),
    ])
    db.commit()
    for site_id, lost in [(1, 0), (1, 3), (1, None), (2, 5)]:
        db.add(Incident(site_id=site_id, user_id=1, type="spill", description="d",
                        severity="low", lost_time_days=lost))
    db.commit()
    db.close()
    return TestClient(main.app)


@pytest.fixture(scope="session")
def auth(client):
    def _headers(email):
        r = client.post("/auth/login", data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}
    return {name: _headers(f"{name}@x.com") for name in ("super", "admin", "mgr")}
