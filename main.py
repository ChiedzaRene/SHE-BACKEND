from fastapi import FastAPI
from fastapi.security import OAuth2PasswordBearer
from database import engine, Base
from models.user import User
from models.site import Site
from models.incident import Incident
from models.corrective_action import CorrectiveAction
from routers import auth, sites, incidents

app = FastAPI(
    title="SHE Management System",
    description="Safety, Health & Environment Management API",
    version="1.0.0",
    swagger_ui_init_oauth={},
)

# Security scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Create all tables
Base.metadata.create_all(bind=engine)

# Include routers
app.include_router(auth.router)
app.include_router(sites.router)
app.include_router(incidents.router)

@app.get("/")
def root():
    return {"message": "SHE Management System API is running "}