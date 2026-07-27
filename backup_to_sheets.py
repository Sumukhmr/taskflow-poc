"""
Backup Supabase tasks → Google Sheets
Run: python backup_to_sheets.py
"""

import gspread
from google.oauth2.service_account import Credentials
from supabase import create_client

# ── CONFIG ──────────────────────────────────────────────────────
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_ID   = "1WnZ6enz4pKVUk-AvhE7578X6kP_zvlqHnej-kFLNsCA"

SUPABASE_URL = "https://asccodcqxrrjtcdbudbv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFzY2NvZGNxeHJyanRjZGJ1ZGJ2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE0OTIwNzUsImV4cCI6MjA5NzA2ODA3NX0.eugIHQgg3FS_jRvt_gBnhWCRebLp6WeP1O-B08pNt94"

# ── CONNECT ──────────────────────────────────────────────────────
print("Connecting to Supabase...")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

print("Connecting to Google Sheets...")
creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=[
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
])
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SPREADSHEET_ID)

# ── FETCH ALL TASKS FROM SUPABASE ────────────────────────────────
print("\nFetching tasks from Supabase...")
res = supabase.table("tasks").select("*").execute()
tasks = res.data or []
print(f"Found {len(tasks)} tasks in Supabase")

if not tasks:
    print("No tasks to backup.")
    exit()

HEADERS = [
    "Task_ID", "Title", "Description", "Assigned_To", "Team",
    "Due_Date", "Priority", "Status", "Created_By", "Created_At",
    "Updated_At", "Sub_Category", "Quadrant", "Notes", "Type",
    "Start_Date", "Attachments"
]

# ── GET OR CREATE TASKS TAB IN GOOGLE SHEETS ────────────────────
print("\nChecking Tasks tab in Google Sheets...")
try:
    tasks_ws = sheet.worksheet("Tasks")
    existing_rows = tasks_ws.get_all_values()
    existing_ids = set(row[0].strip() for row in existing_rows[1:] if row[0].strip())
    print(f"Found {len(existing_ids)} existing tasks in Google Sheets")
except gspread.exceptions.WorksheetNotFound:
    tasks_ws = sheet.add_worksheet(title="Tasks", rows=2000, cols=17)
    tasks_ws.append_row(HEADERS)
    existing_ids = set()
    print("Created Tasks tab with headers")
except Exception as e:
    print(f"Error reading Google Sheets: {e}")
    exit()

# ── BACKUP NEW/MISSING TASKS TO GOOGLE SHEETS ────────────────────
print("\nBacking up tasks...")
added = 0
updated = 0
skipped = 0

def task_to_row(t):
    return [
        t.get("task_id", ""),
        t.get("title", ""),
        t.get("description", "") or "",
        t.get("assigned_to", "") or "",
        t.get("team", "") or "",
        t.get("due_date", "") or "",
        t.get("priority", "") or "",
        t.get("status", "") or "",
        t.get("created_by", "") or "",
        t.get("created_at", "") or "",
        t.get("updated_at", "") or "",
        t.get("sub_category", "") or "",
        t.get("quadrant", "") or "",
        t.get("notes", "") or "",
        t.get("type", "") or "",
        t.get("start_date", "") or "",
        str(t.get("attachments", "[]"))
    ]

for task in tasks:
    task_id = task.get("task_id", "")
    if not task_id:
        skipped += 1
        continue

    row = task_to_row(task)

    if task_id not in existing_ids:
        # New task - append to sheet
        try:
            tasks_ws.append_row(row, table_range='A1')
            print(f"  ✓ Added: {task_id} - {task.get('title', '')[:40]}")
            added += 1
        except Exception as e:
            print(f"  ✗ Failed to add {task_id}: {e}")
            skipped += 1
    else:
        # Existing task - update it
        try:
            all_values = tasks_ws.col_values(1)
            row_num = None
            for i, val in enumerate(all_values):
                if val == task_id:
                    row_num = i + 1
                    break
            if row_num:
                tasks_ws.update(f"A{row_num}:Q{row_num}", [row])
                print(f"  ✓ Updated: {task_id} - {task.get('title', '')[:40]}")
                updated += 1
        except Exception as e:
            print(f"  ✗ Failed to update {task_id}: {e}")
            skipped += 1

print(f"\n✅ Backup complete!")
print(f"   Added:   {added} new tasks")
print(f"   Updated: {updated} existing tasks")
print(f"   Skipped: {skipped}")
print(f"\nGoogle Sheets now has a full backup of all Supabase tasks.")