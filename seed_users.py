import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from database import SessionLocal
from models.user import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
db = SessionLocal()

# ── Users to seed ─────────────────────────────────────────────────────────────
USERS = [
    # ── Admins (shared password) ──────────────────────────────────────────────
    {
        "full_name": "IT Interns",
        "email":     "itglowinterns@outlook.com",
        "password":  "Admin@Glow2025",
        "role":      "admin",
    }]
# ── Insert users ──────────────────────────────────────────────────────────────
print("\n👥 Seeding users...\n")
added = 0
skipped = 0

try:
    for u in USERS:
        existing = db.query(User).filter(User.email == u["email"]).first()
        if existing:
            print(f"  ⏭️  Skipping {u['full_name']} — already exists")
            skipped += 1
            continue

        user = User(
            full_name  = u["full_name"],
            email      = u["email"],
            password   = pwd_context.hash(u["password"]),
            role       = u["role"],
            is_active  = True,
            site_id    = None,
        )
        db.add(user)
        print(f"  ✅ Added {u['role'].upper():10} — {u['full_name']} ({u['email']})")
        added += 1

    db.commit()
    print(f"\n Done! {added} users added, {skipped} skipped.")

    print("\n" + "─" * 55)
    print("📋 LOGIN CREDENTIALS")
    print("─" * 55)
    print("\n ADMINS")
    print(f"  Password (all 3): Admin@Glow2025")
    for u in USERS:
        if u["role"] == "admin":
            print(f"  • {u['email']}")

    print("\n SHE TEAM")
    print(f"  Password (both): SHE@Glow2025!")
    for u in USERS:
        if u["role"] == "she_team":
            print(f"  • {u['email']}")

    print("\n Ask users to change passwords after first login!")
    print("─" * 55)

except Exception as e:
    db.rollback()
    print(f"\n Error: {e}")
    raise
finally:
    db.close()