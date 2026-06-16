#!/usr/bin/env python3
"""
Push TaskFlow files to PythonAnywhere via the Files API, then reload the
web app.

Usage:
    python scripts/push_to_pythonanywhere.py
    python scripts/push_to_pythonanywhere.py app.py index.html migrations/202606.sql
    python scripts/push_to_pythonanywhere.py --no-reload app.py

Token resolution (first match wins):
    1. PYTHONANYWHERE_API_TOKEN environment variable
    2. taskflow_poc/.env  (PYTHONANYWHERE_API_TOKEN=<token>)
    3. ~/.pa_token  (single line: just the token)

Get a token: https://www.pythonanywhere.com/user/sumukhmr/account/#api_token
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

# Windows consoles default to cp1252 which can't print → ✓ ✗ ⚠ etc.
# Force UTF-8 if available so the progress output renders correctly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Hard-coded for this account ────────────────────────────────────
USERNAME       = "sumukhmr"
HOST           = "https://www.pythonanywhere.com"
REMOTE_HOME    = f"/home/{USERNAME}"
WEBAPP_DOMAIN  = f"{USERNAME}.pythonanywhere.com"
TIMEOUT_SECS   = 60

# Default whitelist — what we push when no files are passed on the CLI.
# Keep this tight: this is a deploy action, not a sync. Secrets, test
# artifacts, and user uploads must NEVER be in here.
DEFAULT_FILES = [
    "app.py",
    "index.html",
    "requirements.txt",
]

# Files we always refuse to push, even if explicitly requested, because
# they would clobber server-side state or leak secrets.
NEVER_PUSH = {
    ".env", ".env.local",
    "credentials.json",
    ".pa_token",
}


# ── Helpers ────────────────────────────────────────────────────────
def _read_env_file(path: Path) -> str | None:
    """Best-effort parse of PYTHONANYWHERE_API_TOKEN out of a .env file
    without requiring python-dotenv as a hard dep."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if s.startswith("PYTHONANYWHERE_API_TOKEN"):
                # KEY=value  or  KEY = value  or  KEY="value"
                _, _, val = s.partition("=")
                return val.strip().strip("'").strip('"')
    except Exception:
        pass
    return None


def find_token() -> str | None:
    tok = os.environ.get("PYTHONANYWHERE_API_TOKEN", "").strip()
    if tok:
        return tok
    env_file = project_root() / ".env"
    if env_file.exists():
        tok = _read_env_file(env_file)
        if tok:
            return tok
    pa_token = Path.home() / ".pa_token"
    if pa_token.exists():
        return pa_token.read_text(encoding="utf-8").strip()
    return None


def project_root() -> Path:
    """Walk up from the script's location to taskflow_poc/."""
    return Path(__file__).resolve().parent.parent


def upload_one(local: Path, remote_path: str, token: str) -> tuple[int, str]:
    url = f"{HOST}/api/v0/user/{USERNAME}/files/path{remote_path}"
    with local.open("rb") as f:
        r = requests.post(
            url,
            files={"content": (local.name, f)},
            headers={"Authorization": f"Token {token}"},
            timeout=TIMEOUT_SECS,
        )
    return r.status_code, (r.text or "")[:200]


def reload_webapp(token: str) -> tuple[int, str]:
    url = f"{HOST}/api/v0/user/{USERNAME}/webapps/{WEBAPP_DOMAIN}/reload/"
    r = requests.post(
        url,
        headers={"Authorization": f"Token {token}"},
        timeout=TIMEOUT_SECS,
    )
    return r.status_code, (r.text or "")[:200]


# ── Main ───────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(
        description="Push TaskFlow files to PythonAnywhere and reload the web app."
    )
    p.add_argument(
        "files",
        nargs="*",
        help=("Files to push, relative to taskflow_poc/. "
              f"Defaults: {', '.join(DEFAULT_FILES)}"),
    )
    p.add_argument(
        "--no-reload",
        action="store_true",
        help="Skip the web app reload after uploading.",
    )
    args = p.parse_args()

    token = find_token()
    if not token:
        print("ERROR: No PythonAnywhere API token found.", file=sys.stderr)
        print("", file=sys.stderr)
        print("Get one at: https://www.pythonanywhere.com/user/sumukhmr/account/#api_token",
              file=sys.stderr)
        print("Then pick one:", file=sys.stderr)
        print("  - Add to taskflow_poc/.env:  PYTHONANYWHERE_API_TOKEN=<token>", file=sys.stderr)
        print("  - Or: echo '<token>' > ~/.pa_token && chmod 600 ~/.pa_token", file=sys.stderr)
        print("  - Or: export PYTHONANYWHERE_API_TOKEN='<token>'", file=sys.stderr)
        return 2

    root = project_root()
    targets = args.files or DEFAULT_FILES

    # Refuse to push anything dangerous up-front
    dangerous = [t for t in targets if Path(t).name in NEVER_PUSH]
    if dangerous:
        print(f"ERROR: refusing to push {dangerous} — secrets / sensitive files.",
              file=sys.stderr)
        return 2

    print(f"→ Pushing {len(targets)} file(s) to {USERNAME}@PythonAnywhere ({REMOTE_HOME}/)")

    uploaded: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    for rel in targets:
        rel = rel.replace("\\", "/")
        local = root / rel
        if not local.is_file():
            print(f"   ⚠ SKIP {rel} — not found at {local}")
            skipped.append(rel)
            continue
        remote = f"{REMOTE_HOME}/{rel}"
        size = local.stat().st_size
        code, body = upload_one(local, remote, token)
        if code in (200, 201):
            print(f"   ✓ {rel}  ({size:,} bytes)")
            uploaded.append(rel)
        else:
            print(f"   ✗ {rel}  HTTP {code}: {body}")
            failed.append((rel, f"HTTP {code}: {body}"))

    if not uploaded:
        print("\nNo files were uploaded; skipping reload.")
        return 1

    if args.no_reload:
        print("\n(skipping web app reload — pass without --no-reload to reload)")
    else:
        print(f"\n→ Reloading {WEBAPP_DOMAIN} ...")
        code, body = reload_webapp(token)
        if code == 200:
            print(f"   ✓ reload OK")
        else:
            print(f"   ✗ reload failed (HTTP {code}): {body}")
            return 1

    # Final summary
    print("")
    print(f"✓ Pushed {len(uploaded)} file(s)"
          + (f", skipped {len(skipped)}" if skipped else "")
          + (f", {len(failed)} failed" if failed else "")
          + (" — web app reloaded." if not args.no_reload else "."))
    print(f"  Live at: https://{WEBAPP_DOMAIN}/")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
