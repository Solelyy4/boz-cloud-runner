#!/usr/bin/env python3
"""sapu_queued.py — batalkan run queued yang tersangkut supaya bot baharu dapat runner.

Sebab: setiap repo hanya boleh ada SATU job aktif dalam concurrency group yang sama.
Run queued lama (menunggu > 25 minit) MENYEKAT run bot daripada mula. Bukti 7 Nov 2026:
run 42379226559 dicipta 13:56Z dan masih 'pending' 40 minit kemudian.
"""
import datetime
import json
import os
import subprocess
import sys

USIA_MIN = 25
REPO = os.environ.get("GITHUB_REPOSITORY", "")
SAYA = os.environ.get("GITHUB_RUN_ID", "0")

if not REPO:
    print("GITHUB_REPOSITORY tiada — langkau")
    sys.exit(0)

try:
    out = subprocess.run(
        ["gh", "run", "list", "--repo", REPO, "--workflow", "telegram-hermes",
         "--status", "queued", "-L", "20", "--json", "databaseId,createdAt"],
        capture_output=True, text=True, timeout=60,
    ).stdout
    runs = json.loads(out) if out.strip() else []
except Exception as e:
    print(f"tidak dapat senarai run: {type(e).__name__}: {e}")
    sys.exit(0)

now = datetime.datetime.now(datetime.timezone.utc)
dibatal = 0
for r in runs:
    if str(r.get("databaseId")) == str(SAYA):
        continue
    try:
        c = datetime.datetime.fromisoformat(str(r["createdAt"]).replace("Z", "+00:00"))
    except Exception:
        continue
    usia = (now - c).total_seconds() / 60
    if usia > USIA_MIN:
        print(f"  sapu run queued {r['databaseId']} (usia {usia:.0f} minit)")
        subprocess.run(["gh", "run", "cancel", str(r["databaseId"]), "--repo", REPO],
                       capture_output=True, text=True, timeout=60)
        dibatal += 1

print(f"sapu selesai: {dibatal} run dibatalkan daripada {len(runs)} queued")
