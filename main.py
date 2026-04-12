from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from database import engine, Base
from models.user import User
from models.site import Site
from models.incident import Incident
from models.corrective_action import CorrectiveAction
from models.audit import Audit
from models.legal import Legal
from models.training import Training
from routers import auth, sites, incidents, audits, legal, trainings, users, corrective_actions

app = FastAPI(
    title="SHE Management System",
    description="Safety, Health & Environment Management API",
    version="1.0.0",
    swagger_ui_init_oauth={},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001",
                   "https://yummy-walls-sell.loca.lt"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Create all tables
Base.metadata.create_all(bind=engine)

# Include routers
app.include_router(auth.router)
app.include_router(sites.router)
app.include_router(incidents.router)
app.include_router(audits.router)
app.include_router(legal.router)
app.include_router(trainings.router)
app.include_router(users.router)
app.include_router(corrective_actions.router)

@app.get("/")
def root():
    return {"message": "SHE Management System API is running "}