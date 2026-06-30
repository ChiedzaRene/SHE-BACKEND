<<<<<<< HEAD
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
=======
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d
from database import engine, Base
from models.user import User
from models.site import Site
from models.incident import Incident
from models.corrective_action import CorrectiveAction
from models.audit import Audit
from models.legal import Legal
from models.training import Training
<<<<<<< HEAD
from models.scorecard import Scorecard, ScorecardItem
from routers import auth, scorecard, sites, incidents, audits, legal, trainings, users, corrective_actions


limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])
=======
from routers import auth, sites, incidents, audits, legal, trainings, users, corrective_actions
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d

app = FastAPI(
    title="SHE Management System",
    description="Safety, Health & Environment Management API",
    version="1.0.0",
    swagger_ui_init_oauth={},
)

<<<<<<< HEAD
# Register rate limiter with app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://rococo-cheesecake-99f5b0.netlify.app"
    ],
=======
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000",
        "https://rococo-cheesecake-99f5b0.netlify.app"],
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d
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
<<<<<<< HEAD
app.include_router(scorecard.router, prefix="/legal")

@app.get("/")
def root():
    return {"message": "SHE Management System API is running"}
=======

@app.get("/")
def root():
    return {"message": "SHE Management System API is running "}
>>>>>>> 1407a1a5ec06c717d7b3708ad7ea653135048d5d
