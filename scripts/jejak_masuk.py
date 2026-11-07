#!/usr/bin/env python3
"""jejak_masuk.py - tampal Application.process_update untuk melihat sama ada
update sampai ke python-telegram-bot Application.

MENGAPA
=======
jejak handler (adapter.py) sudah terbukti ditampal (penanda=5, saiz 446,201 pada
kedua-dua salinan) tetapi TIADA [JEJAK] muncul, walaupun kita memegang long-poll
(DIAG: getUpdates ok, 0 update, pending=0). Kita perlu tahu sama ada update
sampai ke Application.process_update:
  * TIDAK sampai  -> masalah sebelum adapter (long-poll/sesi/rangkaian)
  * sampai tetapi handler senyap -> gate menolak sebelum handler

Nota sintaks: corak regex dibina daripada SENARAI bahagian untuk mengelakkan
literal newline dalam sumber Python (kes ini pernah menyebabkan SyntaxError).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PENANDA = "# JEJAK-MASUK-BOZ v1"

# Bahagian corak (tiada newline literal dalam sumber - dicantum dengan join).
CORAK_APP = "".join([
    "(?P<def>",
    chr(10),
    "(?P<ind>[ ",
    chr(92),
    "t]+)",
    "async def process_update",
    chr(92),
    "(",
    "self, update: Update",
    "[^)]*",
    chr(92),
    ")",
    "[^:]*:",
    chr(10),
    ")",
    "(?P<doc>(?P<dind>[ ",
    chr(92),
    "t]*)",
    chr(34),
    chr(34),
    chr(34),
    ".*?",
    chr(34),
    chr(34),
    chr(34),
    chr(10),
    ")?",
])

SNIP_APP = "".join([
    "{ind}# JEJAK-MASUK-BOZ v1: cetak SETIAP update yang sampai ke Application.",
    chr(10),
    "{ind}try:",
    chr(10),
    "{ind}    print(",
    chr(34),
    "[JEJAK-MASUK] process_update: id=%s update_id=%s modul=%s",
    chr(34),
    " % (id(self), getattr(update, ",
    chr(34),
    "update_id",
    chr(34),
    ", ",
    chr(34),
    "?",
    chr(34),
    "), __file__), flush=True)",
    chr(10),
    "{ind}except Exception as _e:",
    chr(10),
    "{ind}    print(",
    chr(34),
    "[JEJAK-MASUK] RALAT: %r",
    chr(34),
    " % (_e,), flush=True)",
    chr(10),
])


def tampal(fail: Path) -> str:
    try:
        teks = fail.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "BACA GAGAL: " + str(e)
    if PENANDA in teks:
        return "sudah"
    m = re.search(CORAK_APP, teks, re.DOTALL)
    if not m:
        return "corak TIDAK padan"
    dind = m.groupdict().get("dind")
    ind = dind if dind else (m.group("ind") + "    ")
    if not ind.strip():
        ind = m.group("ind") + "    "
    titik = m.end("doc") if m.groupdict().get("doc") else m.end("def")
    baru = teks[:titik] + SNIP_APP.format(ind=ind) + teks[titik:]
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


def cari_ptb():
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
        print("JEJAK-MASUK: telegram/ext/_application.py tiada di sys.path")
        print("JEJAK-MASUK: sys.path[:12] = " + repr(sys.path[:12]))
        return 0
    print("JEJAK-MASUK: " + str(len(ptb)) + " fail PTB dijumpai")
    for p in ptb:
        print("  " + tampal(p) + " -> " + str(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
