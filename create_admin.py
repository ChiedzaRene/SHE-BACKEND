import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal
from models.user import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

db = SessionLocal()

try:
    # Check if already exists
    existing = db.query(User).filter(User.email == "chiemashaire@gmail.com").first()
    if existing:
        print("  User already exists — updating to admin...")
        existing.role = "admin"
        existing.is_active = True
        db.commit()
        print(" Updated to admin!")
    else:
        admin = User(
            email="chiemashaire@gmail.com",
            password=pwd_context.hash("Admin@Glow2025"),  # change this after first login
            full_name="Chiedza Mashaire",
            role="admin",
            is_active=True,
            site_id=None,
        )
        db.add(admin)
        db.commit()
        print(" Admin user created!")

    print("\n Login details:")
    print("   Email:    chiemashaire@gmail.com")
    print("   Password: Admin@Glow2025")
    print("\n Change your password after first login!")

except Exception as e:
    db.rollback()
    print(f" Error: {e}")
    raise
finally:
    db.close()