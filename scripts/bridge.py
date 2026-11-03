#!/usr/bin/env python3
"""bridge.py — alat bot awan untuk hantar tugas ke laptop BOZ dan tunggu hasil.

Guna (dari mana-mana mesin yang ada gh auth):
    python bridge.py run "dir C:\\Users\\zahin" --timeout 120
    python bridge.py run "python C:/x.py" --wait 300
    python bridge.py status
    python bridge.py files C:/Users/zahin/Downloads/x.txt   # hantar fail laptop ke bot

Aliran:
  1. tulis jobs/<id8>.json ke repo boz-bridge (via GitHub API — tiada clone)
  2. laptop_bridge.py (SYSTEM task) poll, jalankan, tulis out/<id8>.json
  3. alat ini poll out/ sehingga ada hasil atau tamat masa
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = "Solelyy4/boz-bridge"
GH_LOCAL = Path(r"C:\Users\zahin\AppData\Local\hermes\bin\gh.exe")


def gh_bin() -> str:
    return str(GH_LOCAL) if GH_LOCAL.exists() else "gh"


def api(path: str, method: str = "GET", payload: dict | None = None, raw: bool = False):
    cmd = [gh_bin(), "api", f"repos/{REPO}/{path}", "-X", method]
    body = None
    if payload is not None:
        body = json.dumps(payload)
        cmd += ["--input", "-"]
    r = subprocess.run(cmd, input=body, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return None if not raw else (r.stderr or r.stdout)
    if raw:
        return r.stdout
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def put_file(path: str, text: str, message: str, sha: str | None = None) -> bool:
    payload = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    r = api(f"contents/{path}", "PUT", payload, raw=True)
    return not (isinstance(r, str) and ("HTTP" in r or "error" in r.lower()))


def get_file(path: str) -> tuple[str | None, str | None]:
    r = api(f"contents/{path}")
    if not isinstance(r, dict) or "content" not in r:
        return None, None
    return base64.b64decode(r["content"]).decode("utf-8", errors="replace"), r.get("sha")


def delete_file(path: str, sha: str, message: str) -> bool:
    r = api(f"contents/{path}", "DELETE", {"message": message, "sha": sha}, raw=True)
    return not (isinstance(r, str) and ("HTTP" in r or "error" in r.lower()))


def cmd_run(args) -> int:
    job_id = uuid.uuid4().hex[:12]
    spec = {
        "cmd": args.command,
        "cwd": args.cwd,
        "timeout": args.timeout,
        "reply": True,
        "issued": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "from": "boz-cloud-bot",
    }
    if not put_file(f"jobs/{job_id}.json", json.dumps(spec, ensure_ascii=False, indent=1), f"job {job_id}"):
        print("GAGAL tulis job ke repo", file=sys.stderr)
        return 1
    print(f"job {job_id} dihantar -> menunggu laptop (maks {args.wait}s)")
    deadline = time.time() + args.wait
    while time.time() < deadline:
        time.sleep(10)
        text, sha = get_file(f"out/{job_id}.json")
        if text is None:
            continue
        try:
            res = json.loads(text)
        except json.JSONDecodeError:
            continue
        print(f"\n=== HASIL {job_id} ===")
        print(f"exit={res.get('exit')}  secs={res.get('secs')}  who={res.get('who')}")
        if res.get("out"):
            print("--- stdout ---")
            print(res["out"].rstrip())
        if res.get("err"):
            print("--- stderr ---")
            print(res["err"].rstrip())
        return 0 if res.get("exit") == 0 else 2
    print(f"TAMAT MASA: tiada hasil dalam {args.wait}s. Semak jobs/{job_id}.json di GitHub.", file=sys.stderr)
    return 3


def cmd_status(args) -> int:
    hb, _ = get_file("heartbeat.json")
    if hb is None:
        print("tiada heartbeat — laptop_bridge mungkin tidak jalan")
        return 1
    h = json.loads(hb)
    print(f"laptop: {h.get('host')}  user: {h.get('who')}  pid: {h.get('pid')}")
    print(f"heartbeat: {h.get('ts')}  repo_ready: {h.get('repo_ready')}")
    return 0


def cmd_files(args) -> int:
    src = Path(args.path)
    if not src.exists():
        print(f"fail tidak wujud: {src}", file=sys.stderr)
        return 1
    data = src.read_bytes()
    target = f"tg_out/{uuid.uuid4().hex[:8]}_{src.name}"
    payload = {"message": f"fail dari laptop: {src.name}", "content": base64.b64encode(data).decode("ascii")}
    r = api(f"contents/{target}", "PUT", payload, raw=True)
    ok = not (isinstance(r, str) and ("HTTP" in r or "error" in r.lower()))
    print(f"{'OK' if ok else 'GAGAL'} -> {target}" if ok else (r or "")[:300])
    return 0 if ok else 1


def cmd_queue(args) -> int:
    r = api("contents/jobs")
    if not isinstance(r, list):
        print("tiada job menunggu")
        return 0
    for f in r:
        print(f"{f['name']}  {f.get('size')}b  {f.get('sha','')[:8]}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Jambatan bot awan <-> laptop BOZ")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="hantar arahan ke laptop dan tunggu hasil")
    p.add_argument("command")
    p.add_argument("--cwd", default=None)
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--wait", type=int, default=240)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="semak laptop hidup")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("files", help="hantar fail dari laptop ke repo")
    p.add_argument("path")
    p.set_defaults(func=cmd_files)

    p = sub.add_parser("queue", help="senarai job menunggu")
    p.set_defaults(func=cmd_queue)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
