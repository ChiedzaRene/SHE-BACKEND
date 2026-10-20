"""SHE files: shared by the SHE team / admins with chosen roles; view-only files can't be downloaded."""
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _upload(client, headers, *, title="Fire drill procedure", audience="site_manager", site_id=None,
            view_only=False, name="drill.pdf", content=PDF):
    data = {"title": title, "audience": audience, "view_only": str(view_only).lower()}
    if site_id is not None:
        data["site_id"] = str(site_id)
    return client.post("/she-files/", data=data, files={"file": (name, content, "application/octet-stream")},
                       headers=headers)


def _ids(client, headers):
    return [f["id"] for f in client.get("/she-files/", headers=headers).json()]


def test_only_she_and_admins_can_share(client, auth):
    assert _upload(client, auth["mgr"]).status_code == 403
    assert client.post("/she-files/", data={"title": "x", "audience": "she_team"}).status_code == 401


def test_shared_with_site_managers_is_seen_by_them_and_they_are_notified(client, auth):
    r = _upload(client, auth["she"], title="Permit to work form", name="permit.pdf")
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["audience"] == ["site_manager"] and f["view_only"] is False and f["content_type"] == "application/pdf"
    assert f["id"] in _ids(client, auth["mgr"])
    assert f["id"] in _ids(client, auth["admin"])            # admins oversee every shared file
    notes = client.get("/notifications/", headers=auth["mgr"]).json()["items"]
    assert any(n["resource"] == "she_files" and n["resource_id"] == f["id"] and n["link"] == "/she-files"
               and "Permit to work form" in n["title"] for n in notes)
    # the manager can open and download it
    view = client.get(f"/she-files/{f['id']}/view", headers=auth["mgr"])
    assert view.status_code == 200 and view.content == PDF
    assert view.headers["content-disposition"].startswith("inline")
    down = client.get(f"/she-files/{f['id']}/download", headers=auth["mgr"])
    assert down.status_code == 200 and down.headers["content-disposition"].startswith("attachment")
    assert "permit.pdf" in down.headers["content-disposition"]


def test_view_only_files_open_in_the_app_but_cannot_be_downloaded(client, auth):
    f = _upload(client, auth["she"], title="Confidential audit findings", view_only=True).json()
    assert f["view_only"] is True
    listed = {x["id"]: x for x in client.get("/she-files/", headers=auth["mgr"]).json()}[f["id"]]
    assert listed["can_view"] is True and listed["can_download"] is False and listed["can_delete"] is False
    assert client.get(f"/she-files/{f['id']}/view", headers=auth["mgr"]).status_code == 200
    blocked = client.get(f"/she-files/{f['id']}/download", headers=auth["mgr"])
    assert blocked.status_code == 403 and "view only" in blocked.json()["detail"]
    assert client.get(f"/she-files/{f['id']}/download", headers=auth["admin"]).status_code == 403
    # the person who shared it keeps their own copy
    assert client.get(f"/she-files/{f['id']}/download", headers=auth["she"]).status_code == 200


def test_only_pdfs_and_images_can_be_view_only(client, auth):
    r = _upload(client, auth["she"], name="policy.docx", content=b"PK\x03\x04docx", view_only=True)
    assert r.status_code == 400 and "PDF" in r.json()["detail"]
    ok = _upload(client, auth["she"], name="policy.docx", content=b"PK\x03\x04docx")
    assert ok.status_code == 201 and ok.json()["can_view"] is False
    assert client.get(f"/she-files/{ok.json()['id']}/view", headers=auth["mgr"]).status_code == 415


def test_dangerous_or_oversized_files_are_refused(client, auth):
    assert _upload(client, auth["she"], name="page.html", content=b"<script>alert(1)</script>").status_code == 400
    assert _upload(client, auth["she"], name="logo.svg", content=b"<svg/>").status_code == 400
    assert _upload(client, auth["she"], content=b"").status_code == 400
    assert _upload(client, auth["she"], content=b"x" * (10 * 1024 * 1024 + 1)).status_code == 413
    assert _upload(client, auth["she"], audience="everyone").status_code == 422
    assert _upload(client, auth["she"], title="   ").status_code == 422


def test_files_reach_only_the_chosen_people(client, auth):
    other_site = _upload(client, auth["she"], title="Site B only", site_id=2).json()
    team_only = _upload(client, auth["admin"], title="For the SHE team", audience="she_team").json()
    mgr = _ids(client, auth["mgr"])            # the manager runs site 1
    assert other_site["id"] not in mgr and team_only["id"] not in mgr
    assert client.get(f"/she-files/{other_site['id']}/view", headers=auth["mgr"]).status_code == 404
    assert team_only["id"] in _ids(client, auth["she"])
    mine = _upload(client, auth["she"], title="Site A only", site_id=1).json()
    assert mine["site_name"] == "Site A" and mine["id"] in _ids(client, auth["mgr"])


def test_delete_by_uploader_or_admin_only(client, auth):
    f = _upload(client, auth["she"], title="To be removed").json()
    assert client.delete(f"/she-files/{f['id']}", headers=auth["mgr"]).status_code == 403
    assert client.delete(f"/she-files/{f['id']}", headers=auth["she"]).status_code == 200
    assert f["id"] not in _ids(client, auth["mgr"])
    g = _upload(client, auth["she"], title="Admin removes").json()
    assert client.delete(f"/she-files/{g['id']}", headers=auth["admin"]).status_code == 200


def test_download_is_in_the_audit_log(client, auth):
    f = _upload(client, auth["she"], title="Logged download").json()
    client.get(f"/she-files/{f['id']}/download", headers=auth["mgr"])
    logs = client.get("/audit-logs/", params={"resource": "she_files"}, headers=auth["super"]).json()
    assert any(row["action"] == "DOWNLOAD_SHE_FILE" and row["resource_id"] == f["id"] for row in logs)
