"""Reports: content, access control, CSV safety, PDF output and audit trail."""
import csv
import io
from datetime import date, datetime, timedelta

import pytest

from database import SessionLocal
from models.audit import Audit
from models.audit_log import AuditLog
from models.corrective_action import CorrectiveAction
from models.incident import Incident
from models.legal import Legal
from models.site import Site
from models.site_hours import SiteHours
from models.training import Training
from models.user import User
from services.auth_services import create_access_token, hash_password

MONTH_START = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)  # last month
MONTH = MONTH_START.strftime("%Y-%m")
IN_MONTH = datetime.combine(MONTH_START + timedelta(days=9), datetime.min.time())
OUT_OF_MONTH = IN_MONTH - timedelta(days=70)


@pytest.fixture(scope="module", autouse=True)
def report_data(client):
    """Two sites of our own (ids 70, 71) so these tests don't depend on any other test's data."""
    db = SessionLocal()
    db.add_all([Site(id=70, name="Report Site A", address="a"), Site(id=71, name="Report Site B", address="b")])
    db.add_all([
        User(id=70, email="rm70@x.com", password=hash_password("password123"), role="site_manager", site_id=70),
    ])
    db.flush()
    db.add(SiteHours(site_id=70, period=MONTH_START, hours_worked=50000, entered_by=1))
    for lost, when, typ, desc in [
        (2, IN_MONTH, "injury", "=HYPERLINK(\"http://evil\",\"click\")"),   # lost-time, formula-looking text
        (0, IN_MONTH, "injury", "Cut finger"),
        (0, IN_MONTH, "spill", "Diesel spill"),
        (0, OUT_OF_MONTH, "injury", "Old injury, other month"),
    ]:
        db.add(Incident(site_id=70, user_id=1, type=typ, description=desc, severity="high" if lost else "low",
                        lost_time_days=lost, occurred_at=when))
    db.add(Incident(site_id=71, user_id=1, type="injury", description="Other site", severity="low",
                    lost_time_days=0, occurred_at=IN_MONTH))
    db.add(CorrectiveAction(site_id=70, assigned_to="Tendai", action_taken="Fix pump", status="open",
                            due_date=datetime.now() - timedelta(days=5)))
    db.add(CorrectiveAction(site_id=70, assigned_to="Rudo", action_taken="Signage", status="resolved"))
    db.add(Audit(site_id=70, user_id=1, criteria="Fire safety", score=80, status="open"))
    db.add(Audit(site_id=70, user_id=1, criteria="Spill kit", score=60, status="closed"))
    db.add(Legal(site_id=70, user_id=1, requirements="EMA licence", status="compliant",
                 expiry_date=datetime.now() + timedelta(days=20)))
    db.add(Legal(site_id=70, user_id=1, requirements="Fire certificate", status="non_compliant"))
    db.add(Legal(site_id=70, user_id=1, requirements="Fine licence", status="compliant",
                 expiry_date=datetime.now() + timedelta(days=400)))
    db.add(Training(site_id=70, user_id=1, training_module="Firefighting", personnel="All",
                    trained_employees=8, total_employees=10))
    db.commit()
    db.close()
    yield
    # The metrics tests assert exact global counts, so leave nothing behind
    db = SessionLocal()
    for model in (Incident, CorrectiveAction, Audit, Legal, Training, SiteHours):
        db.query(model).filter(model.site_id.in_([70, 71])).delete(synchronize_session=False)
    db.query(User).filter(User.id == 70).delete(synchronize_session=False)
    db.query(Site).filter(Site.id.in_([70, 71])).delete(synchronize_session=False)
    db.commit()
    db.close()


def kpis(doc):
    return {k["label"]: k["value"] for k in doc["kpis"]}


def table(doc, title):
    return next(t for t in doc["tables"] if t["title"] == title)


def test_requires_login(client):
    for kind in ("performance", "compliance", "incidents", "leaderboard"):
        assert client.get(f"/reports/{kind}").status_code == 401


def test_performance_report_numbers(client, auth):
    r = client.get(f"/reports/performance?site_id=70&month={MONTH}", headers=auth["she"])
    assert r.status_code == 200
    doc = r.json()
    k = kpis(doc)
    # 2 recordable injuries in the month (the old one is another month); 1 lost-time; 50,000 hours
    assert k["TRIR (month)"] == "8.00"           # 2 * 200000 / 50000
    assert k["LTIFR (month)"] == "4.00"          # 1 * 200000 / 50000
    assert k["Hours worked"] == "50,000"
    assert k["Incidents logged"] == "3"          # 2 injuries + spill
    assert k["Open corrective actions"] == "1" and k["Overdue actions"] == "1"
    types = dict(table(doc, "Incidents by type")["rows"])
    assert types == {"Injury": 2, "Spill": 1}
    assert doc["subtitle"].startswith("Report Site A")


def test_month_without_hours_is_na(client, auth):
    prior = (MONTH_START - timedelta(days=1)).strftime("%Y-%m")
    doc = client.get(f"/reports/performance?site_id=70&month={prior}", headers=auth["she"]).json()
    assert kpis(doc)["TRIR (month)"] == "N/A"
    assert any("No hours" in n for n in doc["notes"])


def test_all_sites_performance_has_site_breakdown(client, auth):
    doc = client.get(f"/reports/performance?month={MONTH}", headers=auth["admin"]).json()
    names = [row[0] for row in table(doc, "Sites this month")["rows"]]
    assert "Report Site A" in names and "Report Site B" in names


def test_parameter_validation(client, auth):
    she = auth["she"]
    assert client.get("/reports/performance?month=2026-13", headers=she).status_code == 422
    assert client.get("/reports/performance?month=2099-01", headers=she).status_code == 422
    assert client.get("/reports/performance?site_id=9999", headers=she).status_code == 422
    assert client.get("/reports/nonsense", headers=she).status_code == 422
    assert client.get("/reports/incidents?start=2026-02-01&end=2026-01-01", headers=she).status_code == 422
    assert client.get("/reports/incidents?severity=bogus", headers=she).status_code == 422
    assert client.get("/reports/performance?format=xml", headers=she).status_code == 422


def test_site_manager_scoping(client, auth):
    # Minted directly: /auth/login is rate-limited to 5 per minute and the suite logs in a lot
    mgr = {"Authorization": "Bearer " + create_access_token({"sub": "rm70@x.com"})}
    own = client.get(f"/reports/performance?month={MONTH}", headers=mgr)  # site defaults to their own
    assert own.status_code == 200 and own.json()["subtitle"].startswith("Report Site A")
    assert client.get("/reports/performance?site_id=71", headers=mgr).status_code == 403
    assert client.get("/reports/leaderboard", headers=mgr).status_code == 403
    inc = client.get("/reports/incidents?start=2000-01-01", headers=mgr).json()
    assert {r[1] for r in inc["tables"][0]["rows"]} == {"Report Site A"}  # never another site's incidents


def test_compliance_report(client, auth):
    doc = client.get("/reports/compliance?site_id=70", headers=auth["she"]).json()
    k = kpis(doc)
    assert k["Audits on record"] == "2" and k["Average audit score"] == "70.0" and k["Open audits"] == "1"
    assert k["Legal: expired / non-compliant"] == "1"
    assert k["Legal: expiring in 60 days"] == "1"
    assert k["Training coverage"] == "80%"
    attention = {row[1] for row in table(doc, "Legal records needing attention")["rows"]}
    assert attention == {"Fire certificate", "EMA licence"}  # the licence 400 days out is fine


def test_incident_register_filters(client, auth):
    she = auth["she"]
    start = (MONTH_START - timedelta(days=100)).isoformat()
    doc = client.get(f"/reports/incidents?site_id=70&start={start}", headers=she).json()
    assert kpis(doc)["Incidents"] == "4"
    only_spill = client.get(f"/reports/incidents?site_id=70&start={start}&type=spill", headers=she).json()
    assert [r[3] for r in only_spill["tables"][0]["rows"]] == ["Spill"]
    high = client.get(f"/reports/incidents?site_id=70&start={start}&severity=HIGH", headers=she).json()
    assert kpis(high)["Incidents"] == "1"
    narrow = client.get(f"/reports/incidents?site_id=70&start={MONTH_START}&end={MONTH_START + timedelta(days=30)}",
                        headers=she).json()
    assert kpis(narrow)["Incidents"] == "3"


def test_leaderboard_ranking_puts_no_data_sites_last(client, auth):
    doc = client.get("/reports/leaderboard?period=ytd", headers=auth["she"]).json()
    rows = table(doc, "Ranked by TRIR (lowest first)")["rows"]
    status = {r[1]: r for r in rows}
    assert status["Report Site B"][5] == "N/A" and status["Report Site B"][0] == ""   # unranked
    assert status["Report Site B"][9] == "No hours data"
    ranked = [r[0] for r in rows if r[0] != ""]
    assert ranked == sorted(ranked)
    na_positions = [i for i, r in enumerate(rows) if r[5] == "N/A"]
    ranked_positions = [i for i, r in enumerate(rows) if r[5] != "N/A"]
    assert not ranked_positions or not na_positions or max(ranked_positions) < min(na_positions)


def test_csv_export_neutralises_formulas(client, auth):
    start = (MONTH_START - timedelta(days=100)).isoformat()
    r = client.get(f"/reports/incidents?site_id=70&start={start}&format=csv", headers=auth["she"])
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="she-incidents-' in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    cells = [c for row in rows for c in row]
    assert "'=HYPERLINK(\"http://evil\",\"click\")" in cells      # prefixed, so Excel shows text
    assert not any(c.startswith("=") for c in cells)
    assert "Description" in cells and "Cut finger" in cells


def test_pdf_export(client, auth):
    for kind, extra in [("performance", f"&month={MONTH}"), ("compliance", ""), ("incidents", "&start=2000-01-01"),
                        ("leaderboard", "")]:
        r = client.get(f"/reports/{kind}?site_id=70&format=pdf{extra}" if kind != "leaderboard"
                       else "/reports/leaderboard?format=pdf", headers=auth["she"])
        assert r.status_code == 200, (kind, r.text[:200])
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF") and len(r.content) > 1500
        assert r.headers["content-disposition"].endswith('.pdf"')


def test_pdf_survives_markup_in_data(client, auth):
    """Text that looks like markup must not break the PDF builder."""
    db = SessionLocal()
    db.add(Incident(site_id=70, user_id=1, type="injury", description="<b>unclosed <i>& <para> tags", severity="low",
                    lost_time_days=0, occurred_at=IN_MONTH))
    db.commit()
    db.close()
    r = client.get("/reports/incidents?site_id=70&start=2000-01-01&format=pdf", headers=auth["she"])
    assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_exports_are_audit_logged_but_screen_views_are_not(client, auth):
    db = SessionLocal()
    before = db.query(AuditLog).filter(AuditLog.action == "EXPORT_REPORT").count()
    client.get("/reports/compliance?site_id=70", headers=auth["she"])               # screen: not logged
    assert db.query(AuditLog).filter(AuditLog.action == "EXPORT_REPORT").count() == before
    client.get("/reports/compliance?site_id=70&format=csv", headers=auth["she"])
    client.get("/reports/compliance?site_id=70&format=pdf", headers=auth["admin"])
    db.expire_all()
    rows = db.query(AuditLog).filter(AuditLog.action == "EXPORT_REPORT").all()
    db.close()
    assert len(rows) == before + 2
    assert any("CSV" in r.details for r in rows) and any("PDF" in r.details for r in rows)


def test_csv_numbers_have_no_thousands_separators(client, auth):
    text = client.get(f"/reports/performance?site_id=70&month={MONTH}&format=csv",
                      headers=auth["she"]).content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    assert ["Hours worked", "50000"] in rows
