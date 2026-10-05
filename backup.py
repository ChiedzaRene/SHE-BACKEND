import os
import json
import datetime
from dotenv import load_dotenv
import psycopg2

load_dotenv()

_url = os.getenv("SUPABASE_URL")
if not _url:
    raise SystemExit("SUPABASE_URL is not set")
CONNECTION_STRING = _url.replace("SUPABASE_URL=", "").strip()

# Never write credentials into a backup file: password hashes can be cracked offline.
# Restore users from the database's own backups, or have them reset passwords.
EXCLUDED_COLUMNS = {"users": {"password"}}

TABLES = [
    'users', 'sites', 'incidents', 'corrective_actions',
    'audits', 'legal', 'trainings', 'inspections',
    'scorecards', 'scorecard_items', 'site_hours', 'app_settings', 'audit_logs',
]

def backup():
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'glow_she_backup_{timestamp}.json'
    backup_data = {}

    try:
        conn = psycopg2.connect(CONNECTION_STRING)
        cursor = conn.cursor()

        for table in TABLES:
            try:
                cursor.execute(f'SELECT * FROM {table}')
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                skip = EXCLUDED_COLUMNS.get(table, set())
                backup_data[table] = [
                    {c: v for c, v in zip(columns, row) if c not in skip} for row in rows
                ]
                print(f'Backed up {table}: {len(rows)} rows')
            except Exception as e:
                print(f'Skipped {table}: {e}')
                conn.rollback()

        cursor.close()
        conn.close()

        # Owner-only permissions: the file contains incident and personal data
        fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as f:
            json.dump(backup_data, f, indent=2, default=str)

        print(f'\nBackup saved as {filename}')

    except Exception as e:
        print(f'Backup failed: {e}')

if __name__ == "__main__":
    backup()