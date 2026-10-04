# SHE Management System - Backend

FastAPI backend for the Glow Petroleum **Safety, Health & Environment** dashboard: incidents,
corrective actions, audits, inspections, legal compliance, trainings, scorecards and site
performance (TRIR / LTIFR).

## Setup

```bash
python -m venv venv && source venv/bin/activate      # Windows: .\venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env                                  # then fill in the values
uvicorn main:app --reload
```

Required environment variables (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL (or SQLite for local tests) connection string |
| `SECRET_KEY` | JWT signing key, **32+ characters**. The app refuses to start without it. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ENABLE_DOCS` | `true` to expose `/docs` and `/redoc` (off by default) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime, default 480 |
| `EXTRA_CORS_ORIGINS` | Extra allowed frontend origins, comma-separated |
| `SENTRY_DSN` | Optional error monitoring (`pip install sentry-sdk`) |

## First user

There are no default accounts and no credentials in the repo. Create the first admin with:

```bash
python create_user.py --email you@example.com --role super_admin --name "Your Name"
```

Roles: `super_admin`, `admin`, `she_team`, `site_manager` (site managers only see their own site).

## Safety metrics

TRIR and LTIFR are calculated in `services/safety_metrics.py` and nowhere else, per 200,000 hours:

* **Recordable incident** = an incident of type `injury`
* **Lost-time injury** = a recordable incident with `lost_time_days > 0`
* **Hours worked** are entered monthly per site by the SHE team (`PUT /site-hours/`)
* Only months with hours entered count. A site with no hours has a rate of `null` (shown as N/A).

`GET /incidents/metrics/by-site?period=12m|ytd` returns every site's figures in one call.

## Reports

`GET /reports/{kind}` where kind is `performance` (monthly, per site or all sites), `compliance`,
`incidents` (register with date, type and severity filters) or `leaderboard` (site comparison).
Add `format=csv` or `format=pdf` to download; the default `json` powers the on-screen view.
All three come from one builder (`services/reports.py`), so they always agree.

* Site managers are limited to their own site and cannot run the site comparison.
* CSV cells that start with `=`, `+`, `-` or `@` are neutralised so Excel cannot run them as formulas.
* CSV and PDF downloads are recorded in the audit log (`EXPORT_REPORT`); on-screen views are not.

## Settings

* `POST /auth/change-password` and `PATCH /users/me` let any user change their own password and name
  (wrong current password returns 400, never 401, so the frontend does not sign the user out).
* `GET/PUT /settings/safety-targets`: the TRIR/LTIFR warning limits (default 1.5 / 0.5 per 200,000 hours).
  Everyone can read them; admins can change them, and every change is audited. Reports use them too.
* `GET /audit-logs/export` (super admin only): the filtered log as a PDF (newest 2000 entries, UTC).
  Exports are logged as `EXPORT_AUDIT_LOG`.
* `GET /audit-logs/` (super admin only): filter by `user`, `action`, `resource`, `start`, `end`; page with
  `limit`/`offset`; total in `X-Total-Count`. `/audit-logs/facets` lists the actions and areas.

## Deleting users

Admins can delete users (not super admins; only a super admin can). A user who has recorded incidents,
audits, inspections, legal or training records, scorecards or hours can't be deleted: the API answers `409`
with what they recorded and suggests deactivating the account (`is_active: false`), which blocks sign-in but
keeps their records attributed.

## Password security

* **Sign out everywhere:** each user has a `token_version`, bumped whenever their password changes or is
  reset. Tokens carry the version they were issued with, so older sessions stop working. When you change
  your *own* password the response includes a fresh token so that session continues.
* **Forced change:** accounts an admin creates, and accounts whose password an admin resets, are flagged
  `must_change_password`. Until the user picks their own password the API answers `403` with code
  `password_change_required` for everything except `GET/PATCH /users/me` and `POST /auth/change-password`.
  An admin setting their *own* password through the Users page is a normal change (nothing forced).
* **Audit:** admin resets are logged as `RESET_PASSWORD` (never the password).
* The two new columns are added to existing databases automatically at startup (`services/migrations.py`);
  tokens issued before this feature keep working until their normal expiry.

## API notes

* List endpoints accept optional `?limit=&offset=`; with a limit the total is returned in the
  `X-Total-Count` header. Without a limit they return everything, as before.
* Inspection files are served from `/uploads/inspections/{file}` to logged-in users with access
  to that site. Allowed types: JPG, PNG, PDF (10 MB max).
* Uploads are stored on local disk, which is wiped on every Render redeploy. Move them to object
  storage before relying on them.

## Tests and CI

```bash
pytest -q
ruff check . --select E9,F63,F7,F82
```

GitHub Actions runs both on every pull request. `backup.py` writes a JSON backup of the main
tables (password hashes are excluded and the file is created owner-only).
