"""
Push TaskFlow to Vercel.

Usage:
    python scripts/push_to_vercel.py          # deploys to production
    python scripts/push_to_vercel.py --preview # deploys as preview (no --prod flag)

Requirements:
    - Vercel CLI installed: npm install -g vercel
    - Already logged in: vercel login
    - Project already linked: vercel link  (first time only)
    - Environment variables set on Vercel dashboard or via: vercel env add
"""

import subprocess
import sys
import shutil
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIEW = "--preview" in sys.argv


def run(cmd, **kwargs):
    return subprocess.run(cmd, shell=True, cwd=ROOT, **kwargs)


def check_vercel_cli():
    if shutil.which("vercel") is None:
        print("✗ Vercel CLI not found. Install it with:")
        print("    npm install -g vercel")
        print("  Then log in:")
        print("    vercel login")
        sys.exit(1)


def deploy():
    prod_flag = "" if PREVIEW else " --prod"
    mode = "preview" if PREVIEW else "production"
    print(f"Deploying TaskFlow to Vercel ({mode})…")

    result = run(f"vercel{prod_flag}", capture_output=False)

    if result.returncode != 0:
        print(f"\n✗ Deploy failed (exit {result.returncode})")
        sys.exit(result.returncode)

    print(f"\n✓ Deploy complete ({mode})")
    if not PREVIEW:
        print("  Your app is live on Vercel production.")


if __name__ == "__main__":
    check_vercel_cli()
    deploy()
