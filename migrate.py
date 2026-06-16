"""
One-time migration script: Google Sheets → Supabase
Run this ONCE from your local machine:  python migrate.py
"""

import os
import json
import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from supabase import create_client

load_dotenv()

# ── CONFIG ──────────────────────────────────────────────────────
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
SPREADSHEET_ID          = os.environ.get("SPREADSHEET_ID", "")
SUPABASE_URL            = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY            = os.environ.get("SUPABASE_KEY", "")

if not all([GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID, SUPABASE_URL, SUPABASE_KEY]):
    raise RuntimeError("Missing required env vars. Check your .env file.")

# ── CONNECT ──────────────────────────────────────────────────────
print("Connecting to Google Sheets...")
creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = Credentials.from_service_account_info(creds_info, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID)

print("Connecting to Supabase...")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── MIGRATE TEAMS ────────────────────────────────────────────────
print("\n--- Migrating Teams ---")
try:
    teams_ws = sheet.worksheet("Teams")
    rows = teams_ws.get_all_values()
    teams = [row[0].strip() for row in rows[1:] if row[0].strip()]
    for team in teams:
        try:
            supabase.table("teams").insert({"team_name": team}).execute()
            print(f"  ✓ {team}")
        except Exception as e:
            print(f"  ⚠ {team} (skipped: {e})")
    print(f"Teams done: {len(teams)}")
except Exception as e:
    print(f"Teams failed: {e}")

# ── MIGRATE USERS ────────────────────────────────────────────────
print("\n--- Migrating Users ---")
try:
    users_ws = sheet.worksheet("Users")
    rows = users_ws.get_all_values()
    migrated = 0
    for row in rows[1:]:
        if not row[0].strip():
            continue
        # Pad row to 4 columns
        row = list(row) + [""] * (4 - len(row))
        user = {
            "name":     row[0].strip(),
            "team":     row[1].strip() if len(row) > 1 else "",
            "email":    row[2].strip() if len(row) > 2 else "",
            "password": row[3].strip() if len(row) > 3 else ""
        }
        try:
            supabase.table("users").insert(user).execute()
            print(f"  ✓ {user['name']}")
            migrated += 1
        except Exception as e:
            print(f"  ⚠ {user['name']} (skipped: {e})")
    print(f"Users done: {migrated}")
except Exception as e:
    print(f"Users failed: {e}")

# ── MIGRATE TASKS ────────────────────────────────────────────────
print("\n--- Migrating Tasks ---")
try:
    tasks_ws = sheet.worksheet("Tasks")
    rows = tasks_ws.get_all_values()
    migrated = 0
    failed = 0
    batch = []

    for row in rows[1:]:
        if not row[0].strip():
            continue
        # Pad to 14 columns (original schema)
        row = list(row) + [""] * (14 - len(row))
        task = {
            "task_id":      row[0].strip(),
            "title":        row[1].strip(),
            "description":  row[2].strip(),
            "assigned_to":  row[3].strip(),
            "team":         row[4].strip(),
            "due_date":     row[5].strip(),
            "priority":     row[6].strip() or "medium",
            "status":       row[7].strip() or "todo",
            "created_by":   row[8].strip(),
            "created_at":   row[9].strip(),
            "updated_at":   row[10].strip(),
            "sub_category": row[11].strip(),
            "quadrant":     row[12].strip() or "q2",
            "notes":        row[13].strip(),
            # New columns with defaults
            "type":         "",
            "start_date":   "",
            "attachments":  []
        }

        # Normalize priority/status/quadrant
        if task["priority"] not in ["high","medium","low"]:
            task["priority"] = "medium"
        if task["status"] not in ["todo","just","progress","hold","blocked","review","done"]:
            task["status"] = "todo"
        if task["quadrant"] not in ["q1","q2","q3","q4"]:
            task["quadrant"] = "q2"

        batch.append(task)

        # Insert in batches of 20
        if len(batch) >= 20:
            try:
                supabase.table("tasks").insert(batch).execute()
                migrated += len(batch)
                print(f"  ✓ Batch of {len(batch)} tasks inserted ({migrated} total)")
                batch = []
            except Exception as e:
                print(f"  ✗ Batch failed: {e}")
                failed += len(batch)
                batch = []

    # Insert remaining
    if batch:
        try:
            supabase.table("tasks").insert(batch).execute()
            migrated += len(batch)
            print(f"  ✓ Final batch of {len(batch)} tasks inserted")
        except Exception as e:
            print(f"  ✗ Final batch failed: {e}")
            failed += len(batch)

    print(f"Tasks done: {migrated} migrated, {failed} failed")
except Exception as e:
    print(f"Tasks failed: {e}")

# ── MIGRATE ACTIVITY LOG ─────────────────────────────────────────
print("\n--- Migrating Activity Log ---")
try:
    act_ws = sheet.worksheet("Activity_Log")
    rows = act_ws.get_all_values()
    migrated = 0
    batch = []
    for row in rows[1:]:
        if not row[0].strip():
            continue
        row = list(row) + [""] * (6 - len(row))
        entry = {
            "timestamp":  row[0].strip(),
            "username":   row[1].strip(),
            "action":     row[2].strip(),
            "task_id":    row[3].strip(),
            "task_title": row[4].strip(),
            "details":    row[5].strip()
        }
        batch.append(entry)
        if len(batch) >= 50:
            try:
                supabase.table("activity_log").insert(batch).execute()
                migrated += len(batch)
                print(f"  ✓ {migrated} activity entries inserted")
                batch = []
            except Exception as e:
                print(f"  ✗ Batch failed: {e}")
                batch = []
    if batch:
        try:
            supabase.table("activity_log").insert(batch).execute()
            migrated += len(batch)
        except Exception as e:
            print(f"  ✗ Final batch failed: {e}")
    print(f"Activity done: {migrated} entries")
except Exception as e:
    print(f"Activity log failed: {e}")

print("\n✅ Migration complete!")
print("You can now switch app.py to the Supabase version.")
