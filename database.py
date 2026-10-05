import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Force it to read the Render environment variable first!
DATABASE_URL = os.getenv("DATABASE_URL")

# Quick fix for Render/SQLAlchemy compatibility if your URL starts with 'postgres://'
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if not DATABASE_URL:
    raise SystemExit("DATABASE_URL is not set. Add it in Render's Environment settings (or .env locally).")

# Give up on an unreachable database after 10 seconds instead of hanging (e.g. a paused Supabase project)
connect_args = {"connect_timeout": 10} if DATABASE_URL.startswith("postgresql") else {}

# pool_pre_ping drops connections the host closed while idle (common on Render/Supabase)
# instead of failing the first request after a quiet period.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()