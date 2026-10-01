"""TRIR / LTIFR: 200,000-hour basis, recordable = injury, hours entered monthly by SHE team."""
from datetime import date

from database import SessionLocal
from models.incident import Incident
from models.site_hours import SiteHours
from services.safety_metrics import combine, compute_by_site, window_start


def _this_month():
    return date.today().strftime("%Y-%m")


def test_window_start():
    assert window_start("12m", date(2026, 10, 15)) == date(2025, 11, 1)
    assert window_start("12m", date(2026, 1, 31)) == date(2025, 2, 1)
    assert window_start("ytd", date(2026, 10, 15)) == date(2026, 1, 1)


def test_no_hours_means_no_rate_not_a_fake_one(client, auth):
    g = client.get("/incidents/metrics/global", headers=auth["admin"]).json()
    assert g["total_incidents"] == 5
    assert g["hours_reported"] is False
    assert g["trir"] is None and g["ltifr"] is None


def test_only_she_team_and_admins_can_enter_hours(client, auth):
    body = {"site_id": 1, "month": _this_month(), "hours_worked": 100000}
    assert client.put("/site-hours/", json=body).status_code == 401
    assert client.put("/site-hours/", json=body, headers=auth["mgr"]).status_code == 403
    assert client.put("/site-hours/", json=body, headers=auth["she"]).status_code == 200


def test_hours_validation(client, auth):
    she = auth["she"]
    ok = {"site_id": 1, "month": _this_month(), "hours_worked": 1}
    assert client.put("/site-hours/", json={**ok, "month": "2026-13"}, headers=she).status_code == 422
    assert client.put("/site-hours/", json={**ok, "hours_worked": -5}, headers=she).status_code == 422
    assert client.put("/site-hours/", json={**ok, "month": "2099-01"}, headers=she).status_code == 400
    assert client.put("/site-hours/", json={**ok, "site_id": 999}, headers=she).status_code == 404


def test_rates_use_200k_basis_and_injury_only(client, auth):
    # Site 1 has 100,000 hours this month: 3 recordable injuries, 1 lost-time (the spill is ignored)
    s1 = client.get("/incidents/metrics/1", headers=auth["admin"]).json()
    assert s1["recordable_incidents"] == 3
    assert s1["lost_time_injuries"] == 1
    assert s1["hours_worked"] == 100000
    assert s1["trir"] == 6.0      # 3 * 200000 / 100000
    assert s1["ltifr"] == 2.0     # 1 * 200000 / 100000
    assert s1["total_incidents"] == 4  # still counts the spill


def test_site_without_hours_is_excluded_from_global_rate(client, auth):
    by_site = {r["site_id"]: r for r in client.get("/incidents/metrics/by-site", headers=auth["admin"]).json()}
    assert by_site[2]["trir"] is None and by_site[2]["hours_reported"] is False
    g = client.get("/incidents/metrics/global", headers=auth["admin"]).json()
    # Site 2's injury has no hours behind it, so it must not inflate the global rate
    assert g["trir"] == 6.0 and g["total_incidents"] == 5


def test_updating_hours_replaces_the_month(client, auth):
    body = {"site_id": 1, "month": _this_month(), "hours_worked": 200000}
    assert client.put("/site-hours/", json=body, headers=auth["she"]).status_code == 200
    rows = client.get("/site-hours/?site_id=1", headers=auth["she"]).json()
    assert len(rows) == 1 and rows[0]["hours_worked"] == 200000
    assert client.get("/incidents/metrics/1", headers=auth["admin"]).json()["trir"] == 3.0


def test_site_manager_scoping(client, auth):
    mgr = auth["mgr"]
    rows = client.get("/site-hours/?site_id=2", headers=mgr).json()
    assert all(r["site_id"] == 1 for r in rows)  # forced to own site
    by_site = client.get("/incidents/metrics/by-site", headers=mgr).json()
    assert [r["site_id"] for r in by_site] == [1]
    g = client.get("/incidents/metrics/global", headers=mgr).json()
    assert g["scope"] == "site_1"
    assert client.get("/incidents/metrics/2", headers=mgr).status_code == 403


def test_invalid_period_rejected(client, auth):
    assert client.get("/incidents/metrics/global?period=forever", headers=auth["admin"]).status_code == 422


def test_unreported_month_does_not_inflate_rate(client):
    """An injury in a month with no hours entered is left out; one in a reported month counts."""
    db = SessionLocal()
    try:
        # Use a site no other test touches
        from models.site import Site
        db.add(Site(id=9, name="Site Z", address="z"))
        db.flush()
        db.add(SiteHours(site_id=9, period=date(2026, 8, 1), hours_worked=50000, entered_by=1))
        for when in (date(2026, 8, 10), date(2026, 9, 10)):  # Sep has no hours
            db.add(Incident(site_id=9, user_id=1, type="injury", description="d", severity="low",
                            lost_time_days=1, occurred_at=when))
        db.commit()
        stats = compute_by_site(db, [9], "12m", today=date(2026, 10, 1))[9]
    finally:
        db.close()
    assert stats["recordable_incidents"] == 1
    assert stats["months_reported"] == 1
    assert stats["trir"] == 4.0  # 1 * 200000 / 50000


def test_combine_ignores_sites_without_hours():
    a = {"total_incidents": 2, "recordable_incidents": 2, "lost_time_injuries": 1,
         "hours_worked": 100000.0, "months_reported": 1}
    b = {"total_incidents": 4, "recordable_incidents": 4, "lost_time_injuries": 4,
         "hours_worked": 0.0, "months_reported": 0}
    total = combine([a, b])
    assert total["total_incidents"] == 6
    assert total["recordable_incidents"] == 2 and total["trir"] == 4.0
