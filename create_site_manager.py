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
    target_email = "t@gmail.com"
    target_password = "1234"
    target_site_id = 1  # Ensure this ID exists in your sites table!

    # Check if user already exists
    existing = db.query(User).filter(User.email == target_email).first()
    
    if existing:
        print(f"  User {target_email} already exists — updating to site manager...")
        existing.role = "site_manager"
        existing.is_active = True
        existing.site_id = target_site_id
        existing.password = pwd_context.hash(target_password)
        db.commit()
        print("  Updated user role, site ID, and password successfully!")
    else:
        site_manager = User(
            email=target_email,
            password=pwd_context.hash(target_password),
            full_name="Site Manager",
            role="site_manager",
            is_active=True,
            site_id=target_site_id,
        )
        db.add(site_manager)
        db.commit()
        print("  Site Manager user created!")

    print("\n Login details:")
    print(f"   Email:    {target_email}")
    print(f"   Password: {target_password}")
    print(f"   Role:     site_manager")
    print(f"   Site ID:  {target_site_id}")

except Exception as e:
    db.rollback()
    print(f" Error: {e}")
    raise
finally:
    db.close()