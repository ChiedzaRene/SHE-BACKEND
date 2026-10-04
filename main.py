import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import inspect, text
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from database import engine, Base
from models.user import User
from models.site import Site
from models.incident import Incident
from models.corrective_action import CorrectiveAction
from models.audit import Audit
from models.legal import Legal
from models.training import Training
from models.scorecard import Scorecard, ScorecardItem
from models.site_hours import SiteHours
from models.app_setting import AppSetting
from models.audit_log import AuditLog

from routers import (
    auth, scorecard, sites, incidents, audits, 
    legal, trainings, users, corrective_actions, super_admin, site_hours, reports, settings
)
from routers.inspections import router as inspections, uploads_router
from routers.audit_log import router as audit_log_router

# Optional error monitoring: enabled only when SENTRY_DSN is set and sentry-sdk is installed
if os.getenv("SENTRY_DSN"):
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], traces_sample_rate=0.0, send_default_pii=False)
    except ImportError:
        logging.getLogger("she_portal").warning("SENTRY_DSN is set but sentry-sdk is not installed")

# Setup Rate Limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# Interactive API docs list every endpoint, so they are off unless explicitly enabled
# (set ENABLE_DOCS=true for local development).
DOCS_ENABLED = os.getenv("ENABLE_DOCS", "false").lower() == "true"

app = FastAPI(
    title="SHE Management System",
    description="Safety, Health & Environment Management API",
    version="1.0.0",
    swagger_ui_init_oauth={},
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path not in ("/docs", "/redoc"):  # Swagger/ReDoc load their own scripts
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response

# Register rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://glowshe.netlify.app",
        *[o.strip() for o in os.getenv("EXTRA_CORS_ORIGINS", "").split(",") if o.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Content-Disposition"],
)

# Configure Logging (StreamHandler only for cloud environments like Render)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler()  # Render captures stdout automatically
    ]
)

logger = logging.getLogger("she_portal")

# Security scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Uploads live here but are NOT mounted as public static files: they are served
# through an authenticated route (see routers/inspections.py).
os.makedirs("uploads/inspections", exist_ok=True)

# Schema migrations check
def ensure_inspections_file_url_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("inspections"):
        return

    column_names = {column["name"] for column in inspector.get_columns("inspections")}
    if "file_url" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS file_url VARCHAR"))

# Foreign-key columns used as filters on almost every list/metrics query.
# create_all() never adds indexes to existing tables, so create them idempotently.
INDEXES = [
    ("ix_incidents_site_id", "incidents", "site_id"),
    ("ix_audits_site_id", "audits", "site_id"),
    ("ix_legal_site_id", "legal", "site_id"),
    ("ix_trainings_site_id", "trainings", "site_id"),
    ("ix_inspections_site_id", "inspections", "site_id"),
    ("ix_corrective_actions_site_id", "corrective_actions", "site_id"),
    ("ix_corrective_actions_incident_id", "corrective_actions", "incident_id"),
    ("ix_users_site_id", "users", "site_id"),
    ("ix_audit_logs_timestamp", "audit_logs", "timestamp"),
]


def ensure_indexes() -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        for name, table, column in INDEXES:
            if inspector.has_table(table):
                connection.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))


# Create tables
Base.metadata.create_all(bind=engine)
ensure_inspections_file_url_column()
ensure_indexes()

# Register Routers
app.include_router(auth.router)
app.include_router(sites.router)
app.include_router(incidents.router)
app.include_router(audits.router)
app.include_router(legal.router)
app.include_router(trainings.router)
app.include_router(users.router)
app.include_router(corrective_actions.router)
app.include_router(scorecard.router)
app.include_router(inspections)
app.include_router(uploads_router)
app.include_router(audit_log_router)
app.include_router(super_admin.router)
app.include_router(site_hours.router)
app.include_router(reports.router)
app.include_router(settings.router)

@app.get("/")
def root():
    return {"message": "SHE Management System API is running"}