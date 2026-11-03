#!/usr/bin/env python3
"""migrate_bot.py — tukar bot Telegram lama ke bot baharu TANPA hilang apa-apa.

Guna:
    python scripts/migrate_bot.py --token "123456:AA..." [--name "nama_bot"] [--push]

Apa yang dibuat:
  1. Sahkan token baharu hidup (getMe) + dapat bot ID & username.
  2. Tulis token baharu ke secrets/telegram_bot_token + .real (chmod 600).
  3. Set GitHub secret TELEGRAM_BOT_TOKEN dalam repo runner (gh secret set).
  4. Kemas kini .env tempatan (kalau ada baris TELEGRAM_BOT_TOKEN tak aktif).
  5. Kemas kini fail identiti (SOUL.md/AGENTS.md/config.yaml) yang menyebut bot ID lama.
  6. Commit + push kalau --push.
  7. Cetak ringkasan + arahan dispatch workflow.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes"
SECRETS = HOME / "secrets"
RUNNER = HOME / "cloud" / "repo-runner"
HOME_REPO = HOME / "cache" / "scratch" / "hh"
ENVFILE = HOME / ".env"
TOKEN_FILES = [SECRETS / "telegram_bot_token", SECRETS / "telegram_bot_token.real"]
REPOS = ["Solelyy4/boz-cloud-runner", "Solelyy4/boz-hermes-home"]


def api(token: str, method: str, timeout: int = 20) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def verify_token(token: str) -> dict:
    for attempt in range(3):
        try:
            j = api(token, "getMe")
            if not j.get("ok"):
                sys.exit(f"TOKEN DITOLAK Telegram: {j.get('description')}")
            return j["result"]
        except urllib.error.HTTPError as e:
            body = e.read()[:200].decode("utf-8", "ignore")
            sys.exit(f"TOKEN TIDAK SAH (HTTP {e.code}): {body}")
        except Exception as e:
            if attempt == 2:
                sys.exit(f"GAGAL hubungi Bot API: {type(e).__name__}: {e}")
    raise AssertionError


def read_old_token() -> str:
    for p in TOKEN_FILES:
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    return ""


def mask(t: str) -> str:
    return f"{t[:10]}...{t[-4:]} (len={len(t)})" if len(t) > 16 else "(kosong)"


def write_token(token: str) -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    for p in TOKEN_FILES:
        p.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
    print(f"[1/6] token ditulis ke {len(TOKEN_FILES)} fail secrets")


def update_env(old_id: str, new_id: str) -> None:
    if not ENVFILE.exists():
        print("[2/6] .env tiada — dilangkau")
        return
    text = ENVFILE.read_text(encoding="utf-8")
    changed = 0
    if old_id and old_id != new_id:
        text, n = re.subn(rf"\b{re.escape(old_id)}\b", new_id, text)
        changed += n
    ENVFILE.write_text(text, encoding="utf-8")
    print(f"[2/6] .env: {changed} rujukan bot ID ditukar")


def gh(*args: str, input_text: str | None = None) -> subprocess.CompletedProcess:
    gh_bin = HOME / "bin" / "gh.exe"
    exe = str(gh_bin) if gh_bin.exists() else "gh"
    return subprocess.run([exe, *args], input=input_text, capture_output=True, text=True, timeout=120)


def set_secret(token: str) -> None:
    ok = 0
    for repo in REPOS:
        r = gh("secret", "set", "TELEGRAM_BOT_TOKEN", "--repo", repo, input_text=token)
        if r.returncode == 0:
            print(f"[3/6] secret ditetapkan: {repo}")
            ok += 1
        else:
            print(f"[3/6] GAGAL {repo}: {(r.stderr or r.stdout).strip()[:160]}")
    if ok == 0:
        print("[3/6] AMARAN: tiada secret berjaya ditetapkan — semak gh auth")


def update_identity_files(old_id: str, new_id: str, username: str) -> None:
    if not old_id or old_id == new_id:
        print("[4/6] tiada bot ID lama untuk diganti — dilangkau")
        return
    touched = 0
    for root in (HOME_REPO, RUNNER):
        if not root.exists():
            continue
        for pattern in ("*.md", "*.yaml", "*.yml", "*.py", "*.json"):
            for f in root.rglob(pattern):
                if ".git" in f.parts:
                    continue
                try:
                    txt = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if old_id in txt:
                    f.write_text(txt.replace(old_id, new_id), encoding="utf-8")
                    touched += 1
                    print(f"       dikemas kini: {f.relative_to(root)}")
    print(f"[4/6] {touched} fail identiti dikemas kini (bot ID {old_id} -> {new_id}); username={username}")


def commit_push(message: str) -> None:
    for root in (HOME_REPO, RUNNER):
        if not (root / ".git").exists():
            continue
        for cmd in (
            ["git", "-C", str(root), "add", "-A"],
            ["git", "-C", str(root), "-c", "user.email=bot@local", "-c", "user.name=boz-bot", "commit", "-m", message],
        ):
            subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        r = subprocess.run(["git", "-C", str(root), "push", "origin", "HEAD:master"],
                           capture_output=True, text=True, timeout=180)
        status = "OK" if r.returncode == 0 else (r.stderr or r.stdout).strip()[:160]
        print(f"[5/6] push {root.name}: {status}")


def dispatch() -> None:
    r = gh("workflow", "run", "telegram-hermes", "--repo", REPOS[0])
    print(f"[6/6] dispatch telegram-hermes: {'OK' if r.returncode == 0 else (r.stderr or r.stdout).strip()[:160]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", required=True)
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--dispatch", action="store_true")
    args = ap.parse_args()

    new_token = args.token.strip()
    if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", new_token):
        sys.exit("Format token salah. Sepatutnya <id>:<35+ aksara>.")

    old_token = read_old_token()
    old_id = old_token.split(":")[0] if ":" in old_token else ""

    print(f"token lama: {mask(old_token)}")
    print(f"token baru: {mask(new_token)}")
    info = verify_token(new_token)
    new_id = str(info["id"])
    username = info.get("username", "?")
    print(f"TOKEN BARU HIDUP: @{username} | id {new_id} | nama {info.get('first_name', '')}")
    print()

    write_token(new_token)
    update_env(old_id, new_id)
    set_secret(new_token)
    update_identity_files(old_id, new_id, username)

    if args.push:
        commit_push(f"migrasi ke bot baharu @{username} (id {new_id})")
    else:
        print("[5/6] commit/push dilangkau (tiada --push)")

    if args.dispatch:
        dispatch()
    else:
        print("[6/6] dispatch dilangkau (tiada --dispatch)")

    print()
    print("=== SIAP ===")
    print(f"bot: @{username}  id: {new_id}")
    print("seterusnya: gh workflow run telegram-hermes --repo Solelyy4/boz-cloud-runner")


if __name__ == "__main__":
    main()
