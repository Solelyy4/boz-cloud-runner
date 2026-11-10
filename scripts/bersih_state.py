#!/usr/bin/env python3
"""bersih_state.py — jangan sekali-kali simpan state.db yang separuh ditulis ke git.

PEPIJAT SEBENAR (bot senyap berjam-jam, BOZ nampak ralat "token")
================================================================
`.github/workflows/telegram.yml` menjalankan, selepas bot berhenti:

    cd home
    git add -A
    git commit -m "state $(date -u +%FT%TZ)"

`git add -A` menambah `state.db` — dan pada ketika itu SQLite mungkin belum
checkpoint WAL, jadi fail yang di-commit ialah imej DB yang SEPARUH DITULIS.
Run berikutnya memuat DB rosak itu semula:

    sqlite3.DatabaseError: database disk image is malformed
    PRAGMA integrity_check: *** in database main ***
    Tree 44 page 44 cell 0: invalid page number 603

Kesannya yang BOZ lihat:
  - sesi terakhir terkunci -> `gateway.session_authority: Session ... paused:
    unknown_execution`
  - `gateway_routing` tidak boleh dibaca -> bot tidak tahu sesi mana untuk chat
  - SETIAP mesej memukul sesi mati itu -> bot membalas ralat, dan ralat itu
    mengandungi teks "maximum context length is 32768 tokens" sehingga kita
    tersalah sangka masalahnya model/konteks, bukan DB.

Dan ia BERULANG setiap run kerana DB rosak itu sendiri yang disimpan.

APA YANG SKRIP INI BUAT
=======================
1. `PRAGMA wal_checkpoint(TRUNCATE)` pada state.db — supaya fail di disk
   lengkap dan konsisten (bagus untuk run ini dan untuk apa-apa snapshot).
2. Keluarkan state.db dari indeks git (`git rm --cached`) dan pastikan ia
   dalam .gitignore, supaya tidak pernah di-commit lagi.
3. Laporkan dengan jelas apa yang dilakukan — kegagalan mesti KETARA.

state.db ialah cache tempatan, bukan sumber kebenaran. Yang perlu disimpan
ialah skills/, memories/, config.yaml, sessions/*.json — semuanya fail JSON
yang selamat untuk git.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

DB = "state.db"
GITIGNORE = ".gitignore"


def checkpoint(db: str) -> str:
    """Kosongkan WAL supaya state.db di disk lengkap dan konsisten."""
    if not os.path.exists(db):
        return "state.db tiada (langkau checkpoint)"
    try:
        con = sqlite3.connect(db, timeout=5)
    except sqlite3.Error as e:
        return f"buka state.db gagal (bukan maut): {e}"
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    except sqlite3.Error as e:
        return f"wal_checkpoint gagal (bukan maut): {e}"
    finally:
        con.close()
    return "wal_checkpoint: ok"


def keluar_dari_git(db: str) -> str:
    """Buang state.db dari indeks supaya ia tidak pernah di-commit lagi."""
    notakaki = []
    # Ada dalam indeks? -> rm --cached (fail kekal di disk).
    r = subprocess.run(["git", "ls-files", "--error-unmatch", db],
                       capture_output=True, text=True)
    if r.returncode == 0:
        rm = subprocess.run(["git", "rm", "--cached", "-q", db],
                            capture_output=True, text=True)
        notakaki.append("keluar dari indeks: ok" if rm.returncode == 0
                        else f"git rm --cached gagal: {rm.stderr.strip()[:80]}")
    else:
        notakaki.append("bukan dalam indeks (ok)")

    # Pastikan ada dalam .gitignore.
    ada = False
    if os.path.exists(GITIGNORE):
        with open(GITIGNORE, encoding="utf-8", errors="replace") as f:
            ada = any(b.strip() == db for b in f)
    if not ada:
        with open(GITIGNORE, "a", encoding="utf-8") as f:
            f.write(f"{db}\n")
        notakaki.append(".gitignore: ditambah")
    else:
        notakaki.append(".gitignore: sudah ada")
    return "; ".join(notakaki)


def main() -> int:
    print(f"BERSIH-STATE: checkpoint -> {checkpoint(DB)}", flush=True)
    print(f"BERSIH-STATE: git -> {keluar_dari_git(DB)}", flush=True)
    # Sahkan kesan sebenar, jangan hanya lapor niat.
    r = subprocess.run(["git", "ls-files", DB], capture_output=True, text=True)
    masih = r.stdout.strip()
    if masih:
        print(f"BERSIH-STATE: AMARAN - {DB} MASIH dalam indeks git: {masih}", flush=True)
        return 1
    print(f"BERSIH-STATE: {DB} tidak akan di-commit lagi", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
