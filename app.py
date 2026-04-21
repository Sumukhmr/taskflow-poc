from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import uuid
import threading
import time
import os
import json

app = Flask(__name__)
CORS(app)

# ── CONFIGURATION ───────────────────────────────────────────────
# Works both locally (credentials.json file) and on Render (env vars)
CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID_HERE")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

DEFAULT_TEAMS = ["Sales", "Marketing", "Content", "Product"]

TASKS_SHEET = "Tasks"
TEAMS_SHEET = "Teams"
USERS_SHEET = "Users"

TASK_HEADERS = [
    "Task_ID", "Title", "Description", "Assigned_To", "Team",
    "Due_Date", "Priority", "Status", "Created_By", "Created_At", "Updated_At"
]

TEAM_HEADERS = ["Team_Name"]
USER_HEADERS = ["User_Name", "Team"]

VALID_PRIORITIES = ["Low", "Medium", "High", "Critical"]


# ── IN-MEMORY CACHE ─────────────────────────────────────────────
cache = {
    "tasks": [],
    "teams": [],
    "users": [],
    "last_sync": None
}
cache_lock = threading.Lock()


# ── GOOGLE SHEETS CONNECTION ────────────────────────────────────
def get_client():
    # Option 1: Environment variable (for Render / production)
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        # Option 2: Local file (for development)
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def get_spreadsheet():
    return get_client().open_by_key(SPREADSHEET_ID)


# ── SHEET INITIALIZATION ────────────────────────────────────────
def initialize_sheets():
    spreadsheet = get_spreadsheet()
    existing_sheets = [ws.title for ws in spreadsheet.worksheets()]

    if TASKS_SHEET not in existing_sheets:
        tasks_ws = spreadsheet.add_worksheet(title=TASKS_SHEET, rows=1000, cols=len(TASK_HEADERS))
        tasks_ws.append_row(TASK_HEADERS)
        print(f"Created '{TASKS_SHEET}' tab with headers.")
    else:
        print(f"'{TASKS_SHEET}' tab already exists. Skipping.")

    if TEAMS_SHEET not in existing_sheets:
        teams_ws = spreadsheet.add_worksheet(title=TEAMS_SHEET, rows=100, cols=len(TEAM_HEADERS))
        teams_ws.append_row(TEAM_HEADERS)
        for team in DEFAULT_TEAMS:
            teams_ws.append_row([team])
        print(f"Created '{TEAMS_SHEET}' tab with default teams.")
    else:
        print(f"'{TEAMS_SHEET}' tab already exists. Skipping.")

    if USERS_SHEET not in existing_sheets:
        users_ws = spreadsheet.add_worksheet(title=USERS_SHEET, rows=100, cols=len(USER_HEADERS))
        users_ws.append_row(USER_HEADERS)
        print(f"Created '{USERS_SHEET}' tab with headers.")
    else:
        print(f"'{USERS_SHEET}' tab already exists. Skipping.")

    try:
        default_sheet = spreadsheet.worksheet("Sheet1")
        if len(spreadsheet.worksheets()) > 1:
            spreadsheet.del_worksheet(default_sheet)
            print("Removed default 'Sheet1'.")
    except gspread.exceptions.WorksheetNotFound:
        pass

    print("Sheet initialization complete!")


# ── CACHE SYNC ──────────────────────────────────────────────────
def sync_cache_from_sheets():
    try:
        spreadsheet = get_spreadsheet()

        teams_ws = spreadsheet.worksheet(TEAMS_SHEET)
        team_rows = teams_ws.get_all_values()
        teams = [row[0] for row in team_rows[1:] if row[0].strip()]

        tasks_ws = spreadsheet.worksheet(TASKS_SHEET)
        task_rows = tasks_ws.get_all_values()
        tasks = [row_to_task(row) for row in task_rows[1:] if row[0].strip()]

        users_ws = spreadsheet.worksheet(USERS_SHEET)
        user_rows = users_ws.get_all_values()
        users = []
        for row in user_rows[1:]:
            if row[0].strip():
                users.append({
                    "name": row[0].strip(),
                    "team": row[1].strip() if len(row) > 1 else ""
                })

        with cache_lock:
            cache["teams"] = teams
            cache["tasks"] = tasks
            cache["users"] = users
            cache["last_sync"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print(f"Cache synced: {len(tasks)} tasks, {len(teams)} teams, {len(users)} users")

    except Exception as e:
        print(f"Cache sync failed: {e}")


def background_sync():
    while True:
        time.sleep(60)
        sync_cache_from_sheets()


# ── HELPERS ──────────────────────────────────────────────────────
def generate_task_id():
    return f"TSK-{uuid.uuid4().hex[:6].upper()}"


def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def row_to_task(row):
    if len(row) < len(TASK_HEADERS):
        row.extend([""] * (len(TASK_HEADERS) - len(row)))
    return {
        "task_id": row[0],
        "title": row[1],
        "description": row[2],
        "assigned_to": row[3],
        "team": row[4],
        "due_date": row[5],
        "priority": row[6],
        "status": row[7],
        "created_by": row[8],
        "created_at": row[9],
        "updated_at": row[10]
    }


def find_task_row(tasks_ws, task_id):
    all_values = tasks_ws.col_values(1)
    for i, val in enumerate(all_values):
        if val == task_id:
            return i + 1
    return None


def write_in_background(fn, *args, **kwargs):
    """Run a Google Sheets write operation in a background thread."""
    def wrapper():
        try:
            fn(*args, **kwargs)
        except Exception as e:
            print(f"Background write failed: {e}")
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()


# ── SERVE FRONTEND ──────────────────────────────────────────────
@app.route("/")
def serve_frontend():
    return send_from_directory(".", "index.html")


# ── API: TEAMS ──────────────────────────────────────────────────
@app.route("/api/teams", methods=["GET"])
def get_teams():
    try:
        with cache_lock:
            teams = list(cache["teams"])
        return jsonify({"teams": teams}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: USERS ──────────────────────────────────────────────────
@app.route("/api/users", methods=["GET"])
def get_users():
    try:
        with cache_lock:
            users = list(cache["users"])
        return jsonify({"users": users}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: STATS ──────────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def get_stats():
    try:
        team_filter = request.args.get("team", "").strip()

        with cache_lock:
            all_tasks = list(cache["tasks"])
            teams = list(cache["teams"])

        if team_filter == "Unassigned":
            filtered = [t for t in all_tasks if not t["team"].strip()]
        elif team_filter and team_filter != "All":
            filtered = [t for t in all_tasks if t["team"] == team_filter]
        else:
            filtered = all_tasks

        total = len(filtered)
        completed = sum(1 for t in filtered if t["status"] == "Completed")
        pending = sum(1 for t in filtered if t["status"] == "Pending")

        today = datetime.now().strftime("%Y-%m-%d")
        overdue = sum(
            1 for t in filtered
            if t["status"] == "Pending" and t["due_date"] and t["due_date"] < today
        )

        complete_pct = round((completed / total * 100) if total > 0 else 0)

        urgent = [
            t for t in filtered
            if t["status"] == "Pending" and t["priority"] in ["Critical", "High"]
        ]

        by_function = []
        for team in teams:
            team_tasks = [t for t in all_tasks if t["team"] == team]
            team_total = len(team_tasks)
            team_done = sum(1 for t in team_tasks if t["status"] == "Completed")
            by_function.append({
                "team": team,
                "total": team_total,
                "completed": team_done
            })

        unassigned = [t for t in all_tasks if not t["team"].strip()]
        if unassigned:
            by_function.append({
                "team": "Unassigned",
                "total": len(unassigned),
                "completed": sum(1 for t in unassigned if t["status"] == "Completed")
            })

        return jsonify({
            "total": total,
            "completed": completed,
            "pending": pending,
            "overdue": overdue,
            "complete_pct": complete_pct,
            "urgent": urgent,
            "by_function": by_function
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: GET TASKS ──────────────────────────────────────────────
@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    try:
        team = request.args.get("team", "").strip()

        with cache_lock:
            all_tasks = list(cache["tasks"])

        if team == "Unassigned":
            tasks = [t for t in all_tasks if not t["team"].strip()]
        elif team and team != "All":
            tasks = [t for t in all_tasks if t["team"] == team]
        else:
            tasks = all_tasks

        return jsonify({"tasks": tasks}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: ADD SINGLE TASK ────────────────────────────────────────
@app.route("/api/tasks", methods=["POST"])
def add_task():
    try:
        data = request.get_json()

        if not data.get("title", "").strip():
            return jsonify({"error": "'title' is required."}), 400

        priority = data.get("priority", "Medium").strip()
        if priority not in VALID_PRIORITIES:
            return jsonify({"error": f"Priority must be one of: {', '.join(VALID_PRIORITIES)}"}), 400

        task_id = generate_task_id()
        now = get_timestamp()

        new_row = [
            task_id,
            data["title"].strip(),
            data.get("description", "").strip(),
            data.get("assigned_to", "").strip(),
            data.get("team", "").strip(),
            data.get("due_date", "").strip(),
            priority,
            "Pending",
            data.get("created_by", "System").strip(),
            now,
            now
        ]

        # Update cache first (instant)
        new_task = row_to_task(new_row)
        with cache_lock:
            cache["tasks"].append(new_task)

        # Write to Google Sheets in background
        def sheet_write():
            spreadsheet = get_spreadsheet()
            tasks_ws = spreadsheet.worksheet(TASKS_SHEET)
            tasks_ws.append_row(new_row, table_range='A1')

        write_in_background(sheet_write)

        return jsonify({
            "message": "Task created successfully.",
            "task": new_task
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: BULK ADD TASKS ─────────────────────────────────────────
@app.route("/api/tasks/bulk", methods=["POST"])
def bulk_add_tasks():
    try:
        data = request.get_json()
        titles = data.get("titles", [])

        if not titles:
            return jsonify({"error": "No task titles provided."}), 400

        titles = [t.strip() for t in titles if t.strip()]
        if not titles:
            return jsonify({"error": "All task titles are empty."}), 400

        priority = data.get("priority", "Medium").strip()
        if priority not in VALID_PRIORITIES:
            priority = "Medium"

        assigned_to = data.get("assigned_to", "").strip()
        team = data.get("team", "").strip()
        due_date = data.get("due_date", "").strip()
        now = get_timestamp()

        rows = []
        new_tasks = []
        for title in titles:
            task_id = generate_task_id()
            row = [
                task_id, title, "", assigned_to, team,
                due_date, priority, "Pending",
                data.get("created_by", "System").strip(), now, now
            ]
            rows.append(row)
            new_tasks.append(row_to_task(row))

        # Update cache first (instant)
        with cache_lock:
            cache["tasks"].extend(new_tasks)

        # Write to Google Sheets in background
        def sheet_write():
            spreadsheet = get_spreadsheet()
            tasks_ws = spreadsheet.worksheet(TASKS_SHEET)
            tasks_ws.append_rows(rows, table_range='A1')

        write_in_background(sheet_write)

        return jsonify({
            "message": f"{len(new_tasks)} tasks created successfully.",
            "tasks": new_tasks,
            "count": len(new_tasks)
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: EDIT TASK ──────────────────────────────────────────────
@app.route("/api/tasks/<task_id>", methods=["PUT"])
def edit_task(task_id):
    try:
        data = request.get_json()

        # Read current task from cache
        with cache_lock:
            current_task = next((t for t in cache["tasks"] if t["task_id"] == task_id), None)

        if not current_task:
            return jsonify({"error": "Task not found."}), 404

        updated_row = [
            task_id,
            data.get("title", current_task["title"]).strip(),
            data.get("description", current_task["description"]).strip(),
            data.get("assigned_to", current_task["assigned_to"]).strip(),
            data.get("team", current_task["team"]).strip(),
            data.get("due_date", current_task["due_date"]).strip(),
            data.get("priority", current_task["priority"]).strip(),
            current_task["status"],
            current_task["created_by"],
            current_task["created_at"],
            get_timestamp()
        ]

        # Update cache first (instant)
        updated_task = row_to_task(updated_row)
        with cache_lock:
            cache["tasks"] = [
                updated_task if t["task_id"] == task_id else t
                for t in cache["tasks"]
            ]

        # Write to Google Sheets in background
        def sheet_write():
            spreadsheet = get_spreadsheet()
            tasks_ws = spreadsheet.worksheet(TASKS_SHEET)
            row_num = find_task_row(tasks_ws, task_id)
            if row_num:
                cell_range = f"A{row_num}:K{row_num}"
                tasks_ws.update(cell_range, [updated_row])

        write_in_background(sheet_write)

        return jsonify({
            "message": "Task updated successfully.",
            "task": updated_task
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: TOGGLE STATUS ──────────────────────────────────────────
@app.route("/api/tasks/<task_id>/toggle", methods=["PATCH"])
def toggle_task(task_id):
    try:
        # Read from cache
        with cache_lock:
            current_task = next((t for t in cache["tasks"] if t["task_id"] == task_id), None)

        if not current_task:
            return jsonify({"error": "Task not found."}), 404

        new_status = "Completed" if current_task["status"] == "Pending" else "Pending"
        now = get_timestamp()

        # Update cache first (instant)
        with cache_lock:
            for t in cache["tasks"]:
                if t["task_id"] == task_id:
                    t["status"] = new_status
                    t["updated_at"] = now
                    break

        # Write to Google Sheets in background
        def sheet_write():
            spreadsheet = get_spreadsheet()
            tasks_ws = spreadsheet.worksheet(TASKS_SHEET)
            row_num = find_task_row(tasks_ws, task_id)
            if row_num:
                tasks_ws.update_cell(row_num, 8, new_status)
                tasks_ws.update_cell(row_num, 11, now)

        write_in_background(sheet_write)

        return jsonify({
            "message": f"Task marked as {new_status}.",
            "task_id": task_id,
            "status": new_status
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: DELETE TASK ─────────────────────────────────────────────
@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    try:
        # Check cache
        with cache_lock:
            exists = any(t["task_id"] == task_id for t in cache["tasks"])

        if not exists:
            return jsonify({"error": "Task not found."}), 404

        # Remove from cache first (instant)
        with cache_lock:
            cache["tasks"] = [t for t in cache["tasks"] if t["task_id"] != task_id]

        # Delete from Google Sheets in background
        def sheet_write():
            spreadsheet = get_spreadsheet()
            tasks_ws = spreadsheet.worksheet(TASKS_SHEET)
            row_num = find_task_row(tasks_ws, task_id)
            if row_num:
                tasks_ws.delete_rows(row_num)

        write_in_background(sheet_write)

        return jsonify({
            "message": "Task deleted successfully.",
            "task_id": task_id
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: FORCE REFRESH CACHE ────────────────────────────────────
@app.route("/api/refresh", methods=["POST"])
def refresh_cache():
    try:
        sync_cache_from_sheets()
        return jsonify({"message": "Cache refreshed.", "last_sync": cache["last_sync"]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── STARTUP ─────────────────────────────────────────────────────
def startup():
    """Initialize sheets and cache. Runs on both local dev and gunicorn."""
    print("Initializing Google Sheets...")
    initialize_sheets()

    print("Loading data into cache...")
    sync_cache_from_sheets()

    sync_thread = threading.Thread(target=background_sync, daemon=True)
    sync_thread.start()
    print("Background sync started (every 60 seconds).")


# Run startup when module is loaded (works with gunicorn)
startup()


# ── RUN (local development only) ────────────────────────────────
if __name__ == "__main__":
    print("Starting TaskFlow server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000, use_reloader=False)
