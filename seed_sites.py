import sys
import os

# Make sure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from database import engine, Base, SessionLocal

# Import ALL models so create_all knows about every table
from models.user import User
from models.site import Site
from models.incident import Incident
from models.corrective_action import CorrectiveAction
from models.audit import Audit
from models.legal import Legal
from models.training import Training

# Import scorecard models if they exist
try:
    from models.scorecard import Scorecard, ScorecardItem
    print( "Scorecard models loaded")
except ImportError:
    print(" Scorecard models not found — skipping")

# ── Create all tables ─────────────────────────────────────────────────────────
print(" Creating tables...")
Base.metadata.create_all(bind=engine)
print(" Tables created")

# ── Site data ─────────────────────────────────────────────────────────────────
SITES = [
    {"name": "CBD Centre",          "city": "Harare",       "address": "126 Leopold Takawira, Harare",                          "lat": -17.828671, "lon": 31.044766},
    {"name": "Chans",               "city": "Harare",       "address": "90 Scott Road, Hatfield, Harare",                       "lat": -17.873861, "lon": 31.116295},
    {"name": "Eastern Centre",      "city": "Chitungwiza",  "address": "5 & 6 Guzha Township, Chitungwiza",                     "lat": -17.993746, "lon": 31.071308},
    {"name": "Ebenezer Centre",     "city": "Harare",       "address": "FF 12 Waterfalls Ave Ardbennie, Harare",                "lat": -17.878175, "lon": 31.029403},
    {"name": "Exodus Centre",       "city": "Harare",       "address": "02 Harare Drive, Msasa, Harare",                        "lat": -17.843452, "lon": 31.133947},
    {"name": "Gateway Centre",      "city": "Harare",       "address": "Glen Lorne T/Ship Harare",                              "lat": -17.737510, "lon": 31.201358},
    {"name": "Farmers Centre",      "city": "Mvurwi",       "address": "9 Handsworth Road, Mvurwi",                             "lat": -17.030912, "lon": 30.851775},
    {"name": "OMC 1",               "city": "Kariba",       "address": "3343 Nyamhunga Townships, Kariba",                      "lat": -16.518277, "lon": 28.848983},
    {"name": "OMC 2",               "city": "Kariba",       "address": "466 Mhembwe Close Mahombeko, Kariba",                   "lat": -16.532216, "lon": 28.776025},
    {"name": "Retreat Centre",      "city": "Harare",       "address": "95 Adylinn Westgate, Harare",                           "lat": -17.760481, "lon": 30.969845},
    {"name": "Banana Wealth Centre","city": "Hauna",        "address": "43 Hauna Growth Point, Hauna",                          "lat": -18.2190,   "lon": 28.9415},
    {"name": "Fountain Centre",     "city": "Chivhu",       "address": "Hokonya Shopping Centre, Chivhu",                       "lat": -19.045930, "lon": 31.116873},
    {"name": "Link Centre",         "city": "Murambinda",   "address": "4344 Murambinda Growth Point, Murambinda",               "lat": -19.270270, "lon": 31.652363},
    {"name": "Motion Centre",       "city": "Chipinge",     "address": "77 Moodie Street, Chipinge",                            "lat": -20.192939, "lon": 32.619240},
    {"name": "ZUPCO",               "city": "Mutare",       "address": "15 Riverside Road, Mutare",                             "lat": -18.977667, "lon": 32.661440},
    {"name": "Drive Centre",        "city": "Chiredzi",     "address": "708D Msasa Drive, Chiredzi",                            "lat": -21.042623, "lon": 31.678971},
    {"name": "Traverse Centre",     "city": "Masvingo",     "address": "216-217 Simon Muzenda Street, Masvingo",                "lat": -20.072687, "lon": 30.831362},
    {"name": "Stopover Centre",     "city": "Hwange",       "address": "214 KST Bypass Coronation Drive, Hwange",               "lat": -18.347544, "lon": 26.502423},
    {"name": "Westward Centre",     "city": "Bulawayo",     "address": "55 Plumtree Rd, Belmont, Bulawayo",                     "lat": -20.177835, "lon": 28.570376},
    {"name": "Passover Centre",     "city": "Bulawayo",     "address": "2142A old Khami Road & Basch street, Bulawayo",         "lat": -20.156184, "lon": 28.573651},
    {"name": "Transit Centre",      "city": "Gwanda",       "address": "1097 Saudan Street, Gwanda",                            "lat": -20.936031, "lon": 29.002799},
    {"name": "Westend Centre",      "city": "Tsholotsho",   "address": "253 Tsholotsho Business Centre, Tsholotsho",            "lat": -19.767750, "lon": 27.754429},
    {"name": "Cathedral Centre",    "city": "Gweru",        "address": "Cnr Lobengula & 8th Street, Gweru",                     "lat": -19.4580,   "lon": 29.8150},
    {"name": "Energy Centre",       "city": "Gokwe",        "address": "20 Mateta Road, Gokwe Centre",                          "lat": -18.219909, "lon": 28.941417},
    {"name": "Great Dyke",          "city": "Shurugwi",     "address": "93 Third Avenue, Shurugwi",                             "lat": -19.671391, "lon": 30.001316},
    {"name": "Treasure Centre",     "city": "Zvishavane",   "address": "Stand No. 5748 Gweru RD, Zvishavane",                   "lat": -20.305144, "lon": 30.050495},
    {"name": "Northgate Centre",    "city": "Gweru",        "address": "153 Northgate Heights, Harare Road, Gweru",             "lat": -19.381450, "lon": 29.815556},
    {"name": "Expectations",        "city": "Bulawayo",     "address": "Corner 6th & Josiah Tongogara, Bulawayo",               "lat": -20.152843, "lon": 28.588906},
    {"name": "Resort Centre",       "city": "Victoria Falls","address": "8795 Mkosana, Victoria Falls",                         "lat": -17.944267, "lon": 25.820243},
    {"name": "Lowveld",             "city": "Chipinge",     "address": "683 Checheche Growth Point, Chipinge",                  "lat": -20.760822, "lon": 32.224822},
    {"name": "North East Centre",   "city": "Bindura",      "address": "1207 Harare Road, Bindura",                             "lat": -17.305130, "lon": 31.319641},
    {"name": "Ethics",              "city": "Harare",       "address": "4006 Crowborough, Harare",                              "lat": -17.8500,   "lon": 30.9500},
]

# ── Insert sites ──────────────────────────────────────────────────────────────
db = SessionLocal()
added = 0
skipped = 0

try:
    for s in SITES:
        # Check if site already exists by name
        existing = db.query(Site).filter(Site.name == s["name"]).first()
        if existing:
            print(f"    Skipping '{s['name']}' — already exists")
            skipped += 1
            continue

        # Build the Site object — use whichever fields your Site model has
        site_data = {"name": s["name"]}

        # Add optional fields only if your Site model has them
        # Check your models/site.py and add the matching ones below:
        site_columns = [c.name for c in Site.__table__.columns]

        if "city"     in site_columns: site_data["city"]     = s["city"]
        if "address"  in site_columns: site_data["address"]  = s["address"]
        if "location" in site_columns: site_data["location"] = f"{s['city']} — {s['address']}"
        if "lat"      in site_columns: site_data["lat"]      = s["lat"]
        if "lon"      in site_columns: site_data["lon"]      = s["lon"]
        if "latitude" in site_columns: site_data["latitude"] = s["lat"]
        if "longitude"in site_columns: site_data["longitude"]= s["lon"]

        db.add(Site(**site_data))
        print(f"   Added '{s['name']}' — {s['city']}")
        added += 1

    db.commit()
    print(f"\n Done! {added} sites added, {skipped} skipped.")

except Exception as e:
    db.rollback()
    print(f"\n Error: {e}")
    raise
finally:
    db.close()