"""Create or update a user from the command line. No credentials live in the repo.

Usage:
    python create_user.py --email you@example.com --role super_admin [--name "Full Name"] [--site-id 1]

The password is read from the SEED_PASSWORD env var if set, otherwise prompted for.
"""
import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from database import SessionLocal
from models.user import User
from services.auth_services import hash_password

ROLES = ("site_manager", "she_team", "admin", "super_admin")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument("--name", default=None)
    parser.add_argument("--site-id", type=int, default=None)
    args = parser.parse_args()

    password = os.getenv("SEED_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == args.email).first()
        if user:
            user.role = args.role
            user.is_active = True
            user.password = hash_password(password)
            if args.name:
                user.full_name = args.name
            if args.site_id is not None:
                user.site_id = args.site_id
            print(f"Updated existing user {args.email} -> {args.role}")
        else:
            db.add(User(
                email=args.email,
                password=hash_password(password),
                full_name=args.name,
                role=args.role,
                site_id=args.site_id,
                is_active=True,
            ))
            print(f"Created {args.role} user {args.email}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
