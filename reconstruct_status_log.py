"""
One-time script: Reconstruct status_log for existing tasks from activity_log
Run: python reconstruct_status_log.py
"""

from supabase import create_client
import json
import re
from datetime import datetime

# ── CONFIG ──────────────────────────────────────────────────────
SUPABASE_URL = "https://asccodcqxrrjtcdbudbv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFzY2NvZGNxeHJyanRjZGJ1ZGJ2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODE0OTIwNzUsImV4cCI6MjA5NzA2ODA3NX0.eugIHQgg3FS_jRvt_gBnhWCRebLp6WeP1O-B08pNt94"

# ── CONNECT ──────────────────────────────────────────────────────
print("Connecting to Supabase...")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ── FETCH ALL TASKS ──────────────────────────────────────────────
print("Fetching all tasks...")
tasks_res = supabase.table("tasks").select("task_id, status, created_at, created_by, status_log").execute()
tasks = tasks_res.data or []
print(f"Found {len(tasks)} tasks")

# ── FETCH ALL ACTIVITY LOG ───────────────────────────────────────
print("Fetching activity log...")
# Fetch in batches since there may be many entries
all_activity = []
batch_size = 1000
offset = 0
while True:
    res = supabase.table("activity_log").select("*").order("timestamp", desc=False).range(offset, offset + batch_size - 1).execute()
    batch = res.data or []
    all_activity.extend(batch)
    if len(batch) < batch_size:
        break
    offset += batch_size

print(f"Found {len(all_activity)} activity log entries")

# ── BUILD STATUS HISTORY PER TASK ────────────────────────────────
print("\nReconstructing status history per task...")

# Group activity by task_id
activity_by_task = {}
for entry in all_activity:
    tid = entry.get("task_id", "")
    if not tid:
        continue
    if tid not in activity_by_task:
        activity_by_task[tid] = []
    activity_by_task[tid].append(entry)

def extract_status_from_details(details, action):
    """Extract old and new status from activity log details."""
    if not details:
        return None, None

    # Format: "status: todo → progress"
    match = re.search(r'status:\s*(\w+)\s*(?:→|->)\s*(\w+)', details)
    if match:
        return match.group(1), match.group(2)

    # Format: "Status: progress" (toggle)
    match = re.search(r'[Ss]tatus:\s*(\w+)', details)
    if match and action in ["Status Changed", "Toggled"]:
        return None, match.group(1)

    return None, None

updated = 0
skipped = 0
failed = 0

for task in tasks:
    task_id = task.get("task_id", "")
    current_status = task.get("status", "todo")
    created_at = task.get("created_at", "")
    created_by = task.get("created_by", "System")
    existing_log = task.get("status_log", [])

    # Skip if already has status_log entries
    if existing_log and len(existing_log) > 0:
        skipped += 1
        continue

    # Build status log starting from task creation
    status_log = []

    # Add initial status entry from task creation
    if created_at:
        status_log.append({
            "status": "todo",
            "changed_at": created_at,
            "changed_by": created_by
        })

    # Get all activity entries for this task
    task_activity = activity_by_task.get(task_id, [])

    # Find all status changes from activity log
    for entry in task_activity:
        action = entry.get("action", "")
        details = entry.get("details", "")
        timestamp = entry.get("timestamp", "")
        username = entry.get("username", "System")

        if action in ["Status Changed", "Toggled"]:
            old_status, new_status = extract_status_from_details(details, action)
            if new_status:
                status_log.append({
                    "status": new_status,
                    "changed_at": timestamp,
                    "changed_by": username
                })
        elif action == "Edited" and details and "status:" in details.lower():
            old_status, new_status = extract_status_from_details(details, action)
            if new_status:
                status_log.append({
                    "status": new_status,
                    "changed_at": timestamp,
                    "changed_by": username
                })

    # Sort by timestamp
    def parse_ts(entry):
        ts = entry.get("changed_at", "")
        try:
            return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except:
            try:
                return datetime.fromisoformat(ts)
            except:
                return datetime.min

    status_log.sort(key=parse_ts)

    # Remove duplicates (same status consecutively)
    deduped = []
    for entry in status_log:
        if not deduped or deduped[-1]["status"] != entry["status"]:
            deduped.append(entry)

    # If we only have the initial entry and current status differs, add current status
    if len(deduped) == 1 and current_status != "todo":
        deduped.append({
            "status": current_status,
            "changed_at": task.get("updated_at", created_at),
            "changed_by": "System"
        })

    # Update Supabase
    try:
        supabase.table("tasks").update({"status_log": deduped}).eq("task_id", task_id).execute()
        print(f"  ✓ {task_id}: {len(deduped)} status entries reconstructed")
        updated += 1
    except Exception as e:
        print(f"  ✗ {task_id}: failed - {e}")
        failed += 1

print(f"\n✅ Reconstruction complete!")
print(f"   Updated:  {updated} tasks")
print(f"   Skipped:  {skipped} tasks (already had status_log)")
print(f"   Failed:   {failed} tasks")
print(f"\nStatus history is now available for existing tasks.")