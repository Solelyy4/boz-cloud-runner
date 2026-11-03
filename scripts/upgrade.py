#!/usr/bin/env python3
"""scripts/upgrade.py — BOT BOZ MUAT NAIK DIRI SENDIRI.

Tujuan: bot Telegram BOZ boleh mengubah SOUL.md / AGENTS.md / config.yaml / skills/ dan
menolak (push) ke repo `boz-hermes-home` tanpa BOZ perlu buka Hermes atau bayar apa-apa.

Guna:
    python scripts/upgrade.py --status                    # tunjuk keadaan + commit terkini
    python scripts/upgrade.py --push "mesej commit"       # commit & push semua perubahan
    python scripts/upgrade.py --set key.path value        # set nilai dalam config.yaml
    python scripts/upgrade.py --append SOUL.md "<teks>"   # tambah teks ke hujung fail
    python scripts/upgrade.py --sync-skills               # semak auto_load vs skill dir

Env: BOZ_PAT (token GitHub, scope repo) + BOZ_USER (lalai Solelyy4).
Syarat: dijalankan dari dalam clone repo `boz-hermes-home` (cwd = root repo).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
USER = os.environ.get("BOZ_USER", "Solelyy4")


def git(*args, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"git {' '.join(args)} GAGAL: {r.stderr.strip()[:400]}")
        return False
    return r.stdout.strip() if r.stdout.strip() else True


def pastikan_repo():
    if not (ROOT / ".git").exists():
        print(f"RALAT: {ROOT} bukan repo git. Jalankan dari dalam clone boz-hermes-home.")
        sys.exit(2)
    git("config", "user.email", "bot@local")
    git("config", "user.name", "boz-bot")


def status():
    pastikan_repo()
    print("=== repo:", ROOT)
    print("=== remote:", git("remote", "-v", check=False))
    print("=== 3 commit terkini:")
    print(git("log", "--oneline", "-3", check=False))
    print("=== perubahan belum commit:")
    print(git("status", "--short", check=False) or "(bersih)")
    for f in ("SOUL.md", "AGENTS.md", "config.yaml"):
        p = ROOT / f
        print(f"{f}: {'ADA' if p.exists() else 'TIADA'} ({p.stat().st_size if p.exists() else 0} bait)")
    p = ROOT / "SOUL.md"
    if p.exists():
        soul = p.read_text(encoding="utf-8", errors="ignore")
        print("versi SOUL:", soul.split("\n", 1)[0][:70])


def push(msg):
    pastikan_repo()
    git("add", "-A")
    r = subprocess.run(["git", "commit", "-m", msg], cwd=ROOT, capture_output=True, text=True)
    print("commit:", "dibuat" if r.returncode == 0 else "tiada perubahan / gagal")
    if r.stdout.strip():
        print(r.stdout.strip()[:300])
    git("pull", "--rebase", "-X", "ours", check=False)
    ok = git("push", "origin", "HEAD:master", check=False)
    if ok is False:
        ok = git("push", "origin", "HEAD:main", check=False)
    print("push:", "BERJAYA" if ok else "GAGAL")
    print("HEAD:", git("rev-parse", "--short", "HEAD", check=False))
    return bool(ok)


def set_config(path, value):
    import yaml
    cfg = ROOT / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    keys = path.split(".")
    node = data
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    v = value
    if value.lower() in ("true", "false"):
        v = value.lower() == "true"
    else:
        for cast in (int, float):
            try:
                v = cast(value)
                break
            except ValueError:
                pass
    node[keys[-1]] = v
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"config.yaml: {path} = {v!r} (ditulis, {cfg.stat().st_size} bait)")


def append(path, text):
    p = ROOT / path
    with p.open("a", encoding="utf-8") as fh:
        fh.write("\n" + text + "\n")
    print(f"{path}: +{len(text)} aksara ditambah (jumlah {p.stat().st_size} bait)")


def sync_skills():
    import yaml
    cfg = ROOT / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    ada = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
    auto = set((data.get("skills") or {}).get("auto_load") or [])
    print("skill dir:", len(ada), "| auto_load:", sorted(auto))
    hilang = [s for s in auto if s not in ada]
    print("AMARAN auto_load tiada skill:" , hilang) if hilang else print("auto_load: semua wujud — OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--push", metavar="MSG")
    ap.add_argument("--set", nargs=2, metavar=("PATH", "VALUE"))
    ap.add_argument("--append", nargs=2, metavar=("FILE", "TEXT"))
    ap.add_argument("--sync-skills", action="store_true")
    a = ap.parse_args()
    if a.status:
        status()
    if a.set:
        set_config(*a.set)
    if a.append:
        append(*a.append)
    if a.sync_skills:
        sync_skills()
    if a.push:
        sys.exit(0 if push(a.push) else 1)
    if not any([a.status, a.set, a.append, a.sync_skills, a.push]):
        ap.print_help()


if __name__ == "__main__":
    main()
