#!/usr/bin/env python3
"""jejak_masuk.py - tampal titik MASUK update (process_update / de_json).

DUA LAPIS JEJAK:
  (1) handler-level (dalam adapter.py) - apa yang BOZ hantar sampai ke handler?
  (2) entry-level (dalam python-telegram-bot) - adakah update sampai ke app?

Kalau (1) kosong dan (2) kosong -> update tidak sampai ke proses kita.
Kalau (1) kosong tetapi (2) ada -> gate menolak sebelum handler.

Titik tampalan (cari dari sys.path runtime, bukan dari pokok repo):
  telegram/ext/_application.py : Application.process_update
  telegram/_update.py          : Update.de_json (hanya jika mudah)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PENANDA = "# JEJAK-MASUK-BOZ v1"

SNIP_APP = """{ind}# JEJAK-MASUK-BOZ v1: cetak SETIAP update yang sampai ke Application.
{ind}try:
{ind}    print("[JEJAK-MASUK] process_update dipanggil: id=%s update_id=%s | modul=%s" % (
{ind}        id(self), getattr(update, "update_id", "?"), __file__), flush=True)
{ind}except Exception as _e:
{ind}    print("[JEJAK-MASUK] RALAT process_update: %r" % (_e,), flush=True)
"""

CORAK_APP = r"(?P<def>
(?P<ind>[ \t]+)async def process_update\(self, update: Update[^)]*\)[^:]*:
)(?P<doc>(?P<dind>[ \t]*)\"\"\".*?\"\"\"\n)?"


def tampal(fail: Path, penanda: str, corak: str, snip: str) -> str:
    import re
    try:
        teks = fail.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "BACA GAGAL: " + str(e)
    if penanda in teks:
        return "sudah"
    m = re.search(corak, teks, re.DOTALL)
    if not m:
        return "corak TIDAK padan"
    ind = (m.group("dind") if m.groupdict().get("dind") else (m.group("ind") + "    "))
    if not ind.strip():
        ind = m.group("ind") + "    "
    titik = m.end("doc") if m.groupdict().get("doc") else m.end("def")
    baru = teks[:titik] + snip.format(ind=ind) + teks[titik:]
    try:
        compile(baru, str(fail), "exec")
    except SyntaxError as e:
        return "sintaks rosak (" + str(e) + ") - DIUNDUR"
    simpan = fail.with_suffix(fail.suffix + ".masuk_asli")
    if not simpan.exists():
        try:
            simpan.write_text(teks, encoding="utf-8")
        except OSError:
            pass
    try:
        fail.write_text(baru, encoding="utf-8")
    except OSError as e:
        return "TULIS GAGAL: " + str(e)
    cache = fail.parent / "__pycache__"
    if cache.is_dir():
        for f in cache.glob(fail.stem + "*.pyc"):
            try:
                f.unlink()
            except OSError:
                pass
    return "PATCH OK"


def cari_ptb() -> list[Path]:
    jumpa = []
    for base in sys.path:
        if not base:
            continue
        p = Path(base) / "telegram" / "ext" / "_application.py"
        if p.is_file():
            jumpa.append(p)
    return jumpa


def main() -> int:
    ptb = cari_ptb()
    if not ptb:
        print("JEJAK-MASUK: telegram/ext/_application.py tidak dijumpai di sys.path")
        print("JEJAK-MASUK: sys.path = " + repr(sys.path[:12]))
        return 0
    print("JEJAK-MASUK: " + str(len(ptb)) + " fail PTB dijumpai")
    for p in ptb:
        hasil = tampal(p, PENANDA, CORAK_APP, SNIP_APP)
        print("  " + hasil + " -> " + str(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
