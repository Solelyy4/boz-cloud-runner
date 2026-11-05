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


def cmd_brain(args) -> int:
    """Sisi bot: hantar masalah kepada PERKHIDMATAN JAMBATAN (Hermes penuh di laptop).

    Berbeza daripada `run` (shell mentah): perkhidmatan ini berfikir dengan Hermes penuh
    -- jadi ia bukan sekadar menjalankan arahan, ia menyelesaikan masalah yang bot awan
    tidak dapat selesaikan, dan memulangkan jawapan + bukti.
    """
    import urllib.error
    import urllib.request

    repo = "Solelyy4/boz-bridge"
    branch = "master"
    base = f"https://api.github.com/repos/{repo}/contents"
    tok = (os.environ.get("BOZ_PAT") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not tok:
        print("GAGAL: tiada PAT (BOZ_PAT) untuk jambatan", file=sys.stderr)
        return 1
    job_id = "tg-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
    job = {"id": job_id, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "kind": args.kind, "from": "telegram-bot", "problem": args.problem}
    if args.context:
        try:
            job["context"] = json.loads(args.context)
        except json.JSONDecodeError:
            job["context"] = {"nota": args.context}

    def call(path: str, method: str = "GET", payload: dict | None = None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(f"{base}/{path}?ref={branch}", data=data, method=method)
        req.add_header("Authorization", "Bearer " + tok)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "boz-bridge-bot")
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as exc:
            return exc.code, None
        except Exception:
            return 0, None

    path = f"bridge/in/{job_id}.json"
    code, data = call(path)
    sha = data.get("sha") if code == 200 and isinstance(data, dict) else None
    payload = {"message": f"tanya jambatan {job_id}", "branch": branch,
               "content": base64.b64encode(json.dumps(job, ensure_ascii=False, indent=1).encode()).decode()}
    if sha:
        payload["sha"] = sha
    code, _ = call(path, "PUT", payload)
    if code not in (200, 201):
        print(f"GAGAL hantar job jambatan (HTTP {code})", file=sys.stderr)
        return 1
    print(f"job jambatan {job_id} dihantar -> menunggu Hermes laptop (maks {args.wait}s)")
    deadline = time.time() + args.wait
    while time.time() < deadline:
        time.sleep(5)
        code, data = call(f"bridge/out/{job_id}.json")
        if code == 200 and isinstance(data, dict):
            text = base64.b64decode(data.get("content") or "").decode("utf-8", "replace")
            try:
                res = json.loads(text)
            except json.JSONDecodeError:
                continue
            print("\n=== JAWAPAN JAMBATAN ===")
            print(f"status={res.get('status')} secs={res.get('secs')}")
            print((res.get("answer") or "").rstrip())
            ev = (res.get("evidence") or "").strip()
            if ev:
                print("--- bukti ---")
                print(ev[:1200])
            return 0 if res.get("status") == "ok" else 2
    print(f"TAMAT MASA: laptop tidak menjawab dalam {args.wait}s", file=sys.stderr)
    return 3


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

    p = sub.add_parser("brain", help="tanya Hermes PENUH di laptop (perkhidmatan jambatan)")
    p.add_argument("problem", help="masalah/tugasan yang bot tidak dapat selesaikan")
    p.add_argument("--context", default="", help="JSON konteks (ralat, output alat, dsb.)")
    p.add_argument("--kind", default="help", choices=["help", "probe"])
    p.add_argument("--wait", type=int, default=600)
    p.set_defaults(func=cmd_brain)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
