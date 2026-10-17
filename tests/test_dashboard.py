from datetime import date, datetime, timedelta

import pytest

from database import SessionLocal
from models.corrective_action import CorrectiveAction
from models.incident import Incident
from models.site import Site
from models.site_hours import SiteHours
from services.dashboard import period_range, summarise

TODAY = date(2026, 8, 20)


def test_period_ranges_and_their_comparisons():
    assert period_range("month", TODAY) == ((date(2026, 8, 1), date(2026, 9, 1)), (date(2026, 7, 1), date(2026, 8, 1)))
    assert period_range("last_month", TODAY)[0] == (date(2026, 7, 1), date(2026, 8, 1))
    # Q3 compared with Q2
    assert period_range("quarter", TODAY) == ((date(2026, 7, 1), date(2026, 10, 1)), (date(2026, 4, 1), date(2026, 7, 1)))
    assert period_range("last_quarter", TODAY) == ((date(2026, 4, 1), date(2026, 7, 1)), (date(2026, 1, 1), date(2026, 4, 1)))
    # year to date compared with the same months last year
    assert period_range("ytd", TODAY) == ((date(2026, 1, 1), date(2026, 9, 1)), (date(2025, 1, 1), date(2025, 9, 1)))
    assert period_range("12m", TODAY)[0] == (date(2025, 9, 1), date(2026, 9, 1))
    assert period_range("quarter", date(2026, 1, 5))[1] == (date(2025, 10, 1), date(2026, 1, 1))  # across the year
    with pytest.raises(ValueError):
        period_range("decade", TODAY)


@pytest.fixture()
def two_sites():
    """Two sites with their own hours, injuries and corrective actions in July 2026."""
    db = SessionLocal()
    a, b = Site(id=501, name="Dash A", address="a"), Site(id=502, name="Dash B", address="b", contact_number="+263 1")
    db.add_all([a, b])
    db.commit()
    july = datetime(2026, 7, 10)
    db.add_all([
        SiteHours(site_id=501, period=date(2026, 7, 1), hours_worked=100000, workers=40, entered_by=1),
        SiteHours(site_id=502, period=date(2026, 7, 1), hours_worked=50000, workers=25, entered_by=1),
        # A: 1 injury (lost time) -> TRIR 2.0, LTIFR 2.0 ; B: 2 injuries -> TRIR 8.0, LTIFR 0
        Incident(site_id=501, user_id=1, type="injury", description="d", severity="low", lost_time_days=2, occurred_at=july),
        Incident(site_id=502, user_id=1, type="injury", description="d", severity="low", lost_time_days=0, occurred_at=july),
        Incident(site_id=502, user_id=1, type="Injury", description="d", severity="low", lost_time_days=0, occurred_at=july),
        Incident(site_id=502, user_id=1, type="spill", description="d", severity="low", occurred_at=datetime(2026, 8, 2)),
        # actions: A one closed in 4 days, one open; B one closed in 10 days
        CorrectiveAction(site_id=501, assigned_to="x", action_taken="a1", status="resolved",
                         created_at=july, date_resolved=july + timedelta(days=4)),
        CorrectiveAction(site_id=501, assigned_to="x", action_taken="a2", status="open", created_at=july),
        CorrectiveAction(site_id=502, assigned_to="x", action_taken="b1", status="closed",
                         created_at=july, date_resolved=july + timedelta(days=10)),
    ])
    db.commit()
    yield db
    db.query(CorrectiveAction).filter(CorrectiveAction.site_id.in_([501, 502])).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.site_id.in_([501, 502])).delete(synchronize_session=False)
    db.query(SiteHours).filter(SiteHours.site_id.in_([501, 502])).delete(synchronize_session=False)
    db.query(Site).filter(Site.id.in_([501, 502])).delete(synchronize_session=False)
    db.commit()
    db.close()


def test_each_site_has_its_own_rates_and_all_sites_is_their_average(two_sites):
    s = summarise(two_sites, [501, 502], date(2026, 7, 1), date(2026, 8, 1), TODAY)
    rows = {r["site_id"]: r for r in s["sites"]}
    assert (rows[501]["trir"], rows[501]["ltifr"]) == (2.0, 2.0)
    assert (rows[502]["trir"], rows[502]["ltifr"]) == (8.0, 0.0)
    t = s["totals"]
    assert t["trir"] == 5.0 and t["ltifr"] == 1.0            # (2+8)/2 and (2+0)/2, not pooled
    assert t["hours_worked"] == 150000 and t["workers"] == 65
    assert t["incidents"] == 3 and t["injuries"] == 3 and t["lost_time_injuries"] == 1
    assert s["label"] == "July 2026"


def test_corrective_action_completion_and_days_to_close(two_sites):
    s = summarise(two_sites, [501, 502], date(2026, 7, 1), date(2026, 8, 1), TODAY)
    rows = {r["site_id"]: r for r in s["sites"]}
    assert rows[501]["actions_completion_pct"] == 50.0 and rows[501]["avg_days_to_close"] == 4.0
    assert rows[502]["actions_completion_pct"] == 100.0 and rows[502]["avg_days_to_close"] == 10.0
    t = s["totals"]
    assert t["actions_total"] == 3 and t["actions_completed"] == 2
    assert t["actions_completion_pct"] == 66.7 and t["avg_days_to_close"] == 7.0


def test_incidents_by_month_and_type_for_the_chart(two_sites):
    s = summarise(two_sites, [501, 502], date(2026, 7, 1), date(2026, 9, 1), TODAY)
    months = {m["month"]: m for m in s["by_month"]}
    assert months["2026-07"]["injury"] == 3                 # "Injury" and "injury" count together
    assert months["2026-08"]["spill"] == 1
    assert {t["name"] for t in s["by_type"]} == {"injury", "spill"}
    assert s["label"] == "Jul – Aug 2026"


def test_site_information_is_included(two_sites):
    s = summarise(two_sites, [502], date(2026, 7, 1), date(2026, 8, 1), TODAY)
    row = s["sites"][0]
    assert row["name"] == "Dash B" and row["contact_number"] == "+263 1" and row["workers"] == 25


def test_summary_endpoint_access_and_scope(client, auth):
    r = client.get("/dashboard/summary", params={"period": "quarter"}, headers=auth["admin"])
    assert r.status_code == 200
    body = r.json()
    assert body["period_name"] == "This quarter" and "current" in body and "previous" in body
    assert {row["site_id"] for row in body["current"]["sites"]} >= {1, 2}

    one = client.get("/dashboard/summary", params={"period": "12m", "site_id": 2}, headers=auth["she"]).json()
    assert [row["site_id"] for row in one["current"]["sites"]] == [2]

    # a site manager always gets their own site, whatever they ask for
    mgr = client.get("/dashboard/summary", params={"site_id": 2}, headers=auth["mgr"]).json()
    assert mgr["site_id"] == 1 and [row["site_id"] for row in mgr["current"]["sites"]] == [1]

    assert client.get("/dashboard/summary", params={"period": "forever"}, headers=auth["admin"]).status_code == 422
    assert client.get("/dashboard/summary", params={"site_id": 9999}, headers=auth["admin"]).status_code == 404
    assert client.get("/dashboard/summary").status_code == 401
