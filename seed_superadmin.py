# seed_superadmin.py
import sys
from database import SessionLocal
from models.user import User
from services.auth_services import hash_password

def create_superadmin(email: str, password: str, full_name: str = "Super Admin"):
    db = SessionLocal()
    try:
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == email).first()
        if existing_user:
            print(f"User with email '{email}' already exists. Updating role to 'super_admin'...")
            existing_user.role = "super_admin"
            existing_user.is_active = True
            db.commit()
            print("Successfully updated existing user to 'super_admin'.")
            return

        # Create new Super Admin user
        super_admin = User(
            email=email,
            password=hash_password(password),
            full_name=full_name,
            role="super_admin",
            is_active=True,
            site_id=None  # Super admin is not tied to a single site
        )
        db.add(super_admin)
        db.commit()
        db.refresh(super_admin)
        print(f"Successfully created Super Admin user: {email} (ID: {super_admin.id})")

    except Exception as e:
        db.rollback()
        print(f"Error creating Super Admin: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    # You can customize these credentials or pass them via CLI args
    ADMIN_EMAIL = "chiedza.renem@gmail.com"
    ADMIN_PASSWORD = "H0p3$4"  # Make sure to change this!

    print(f"Seeding Super Admin account: {ADMIN_EMAIL}...")
    create_superadmin(email=ADMIN_EMAIL, password=ADMIN_PASSWORD)