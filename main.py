from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
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
from routers import auth, scorecard, sites, incidents, audits, legal, trainings, users, corrective_actions
from routers.inspections import router as inspections
from routers.audit_log import router as audit_log_router
from models.audit_log import AuditLog
import logging
from routers import super_admin


import os

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(
    title="SHE Management System",
    description="Safety, Health & Environment Management API",
    version="1.0.0",
    swagger_ui_init_oauth={},
)

# Register rate limiter with app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://glowshe.netlify.app",
        "http://192.168.1.162:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("app.log"),  # Saves logs to app.log file
        logging.StreamHandler()          # Outputs logs to console
    ]
)

logger = logging.getLogger("she_portal")

# Security scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Serve file attachments statically
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Make sure directory exists
os.makedirs("uploads/inspections", exist_ok=True)

# Mount the static directory so localhost:8000/uploads/... works
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Keep existing databases compatible with the current inspection model.
def ensure_inspections_file_url_column() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("inspections"):
        return

    column_names = {column["name"] for column in inspector.get_columns("inspections")}
    if "file_url" in column_names:
        return

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS file_url VARCHAR"))


# Create all tables
Base.metadata.create_all(bind=engine)
ensure_inspections_file_url_column()

# Include routers
app.include_router(auth.router)
app.include_router(sites.router)
app.include_router(incidents.router)
app.include_router(audits.router)
app.include_router(legal.router)
app.include_router(trainings.router)
app.include_router(users.router)
app.include_router(corrective_actions.router)
app.include_router(scorecard.router, prefix="/legal")
app.include_router(inspections)
app.include_router(audit_log_router)
app.include_router(super_admin.router)

@app.get("/")
def root():
    return {"message": "SHE Management System API is running"}