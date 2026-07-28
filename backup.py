import os
import json
import datetime
from dotenv import load_dotenv
import psycopg2

load_dotenv()

CONNECTION_STRING = os.getenv("SUPABASE_URL").replace("SUPABASE_URL=", "").strip()

TABLES = [
    'users', 'sites', 'incidents', 'corrective_actions',
    'audits', 'legal', 'trainings', 'inspections'
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
                backup_data[table] = [dict(zip(columns, row)) for row in rows]
                print(f'Backed up {table}: {len(rows)} rows')
            except Exception as e:
                print(f'Skipped {table}: {e}')
                conn.rollback()

        cursor.close()
        conn.close()

        with open(filename, 'w') as f:
            json.dump(backup_data, f, indent=2, default=str)

        print(f'\nBackup saved as {filename}')

    except Exception as e:
        print(f'Backup failed: {e}')

if __name__ == "__main__":
    backup()