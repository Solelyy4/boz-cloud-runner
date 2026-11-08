#!/usr/bin/env python3
"""push_api.py — push fail ke GitHub guna Contents API (kalis perlumbaan).

MENGAPA: bot push `gw_trace.log` setiap 90s, jadi `git push` dari laptop kerap KALAH
perlumbaan dan perubahan hilang SENYAP (git log lokal tunjuk commit yang tidak pernah
sampai ke GitHub). Contents API menulis satu fail pada satu masa dengan SHA terkini —
ia sentiasa berjaya, dan kita SAHKAN dengan membaca semula dari remote.

Guna:
  python push_api.py <repo> <branch> <fail_lokal> <laluan_repo> [mesej]
  python push_api.py Solelyy4/boz-cloud-runner master scripts/x.py scripts/x.py "mesej"
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys

GH = os.path.expandvars(r"%LOCALAPPDATA%\hermes\bin\gh.exe")


def api(*args: str, inp: str | None = None) -> tuple[int, str]:
    r = subprocess.run([GH, "api", *args], capture_output=True, text=True, input=inp)
    return r.returncode, (r.stdout or r.stderr)


def sha_semasa(repo: str, path: str, branch: str) -> str | None:
    rc, out = api(f"repos/{repo}/contents/{path}?ref={branch}", "--jq", ".sha")
    if rc != 0:
        return None
    s = out.strip()
    return s if s and "Not Found" not in s else None


def tulis(repo: str, branch: str, lokal: str, path: str, mesej: str) -> bool:
    if not os.path.exists(lokal):
        print(f"[FAIL] {lokal} tiada")
        return False
    data = open(lokal, "rb").read()
    sha = sha_semasa(repo, path, branch)
    payload = {
        "message": mesej,
        "branch": branch,
        "content": base64.b64encode(data).decode(),
    }
    if sha:
        payload["sha"] = sha
    rc, out = api("-X", "PUT", f"repos/{repo}/contents/{path}", "--input", "-", inp=json.dumps(payload))
    if rc != 0 or '"commit"' not in out:
        print(f"[FAIL] tulis {path}: {out[:200]}")
        return False
    return True


def sahkan(repo: str, branch: str, lokal: str, path: str) -> bool:
    """Baca semula dari REMOTE dan bandingkan bait. Jangan percaya push sahaja."""
    rc, out = api(f"repos/{repo}/contents/{path}?ref={branch}", "--jq", ".content")
    if rc != 0:
        print(f"[FAIL] sahkan {path}: tidak boleh baca")
        return False
    remote = base64.b64decode(out.replace("\n", "")).decode("utf-8", "replace")
    lokal_teks = open(lokal, encoding="utf-8", errors="replace").read()
    # GitHub boleh menyimpan LF; bandingkan tanpa CR untuk elak positif palsu.
    sama = remote.replace("\r\n", "\n") == lokal_teks.replace("\r\n", "\n")
    print(f"[{'PASS' if sama else 'FAIL'}] {path}: remote {len(remote)} bait, lokal {len(lokal_teks)}")
    return sama


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__)
        return 1
    repo, branch, lokal, path = sys.argv[1:5]
    mesej = sys.argv[5] if len(sys.argv) > 5 else f"kemas kini {path}"
    if not tulis(repo, branch, lokal, path, mesej):
        return 1
    return 0 if sahkan(repo, branch, lokal, path) else 1


if __name__ == "__main__":
    sys.exit(main())
