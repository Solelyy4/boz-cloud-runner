#!/usr/bin/env python3
"""jejak_masuk.py - tampal Application.process_update (titik masuk update).

MENGAPA carian venv, bukan HERMES_HOME
=====================================
Bukti (gw_trace.log run 42416974187):
    JEJAK-MASUK: 0 _application.py dijumpai
    JEJAK-MASUK: 2 telegram/__init__.py dijumpai
      -> home/hermes-agent/plugins/platforms/telegram/__init__.py
      -> home/installs/.../workspace/plugins/platforms/telegram/__init__.py
Kedua-duanya plugin Hermes bernama "telegram", BUKAN pakej python-telegram-bot.
PTB tinggal dalam site-packages venv:
    <HERMES_HOME>/installs/<id>/environments/<env>/venv/lib/pythonX.Y/site-packages/telegram/

Strategi carian (berlapis):
  1. sys.path (jika site-packages sudah ada)
  2. <HERMES_HOME>/installs/*/environments/*/venv/lib/python*/site-packages/telegram
  3. <HERMES_HOME>/installs/*/environments/*/venv/Lib/site-packages/telegram (Windows)
  4. rglob generik (sandaran)

Kalau process_update TIDAK pernah cetak -> update tidak sampai ke app.
Kalau ia cetak tetapi handler senyap -> gate menolak sebelum handler.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PENANDA = "# JEJAK-MASUK-BOZ v1"

NL = chr(10)
Q3 = chr(34) * 3
BS = chr(92)
TAB = BS + "t"

CORAK_APP = "".join([
    "(?P<def>", NL,
    "(?P<ind>[ ", TAB, "]+)",
    "async def process_update", BS, "(", "self, update",
    "[^)]*", BS, ")", "[^:]*:", NL,
    ")",
    "(?P<doc>(?P<dind>[ ", TAB, "]*", Q3, ".*?", Q3, NL, ")?",
])

SNIP_APP = "".join([
    "{ind}# JEJAK-MASUK-BOZ v1: cetak setiap update yang sampai ke Application.",
    NL,
    "{ind}try:", NL,
    "{ind}    print(",
    chr(34),
    "[JEJAK-MASUK] process_update id=%s update_id=%s modul=%s",
    chr(34),
    " % (id(self), getattr(update, ", chr(34), "update_id", chr(34),
    ", ", chr(34), "?", chr(34), "), __file__), flush=True)", NL,
    "{ind}except Exception as _e:", NL,
    "{ind}    print(", chr(34), "[JEJAK-MASUK] RALAT: %r", chr(34),
    " % (_e,), flush=True)", NL,
])


def calon_ptb(akar: Path):
    """Senarai laluan _application.py yang munasabah."""
    jumpa = []

    # 1. sys.path
    for base in sys.path:
        if not base:
            continue
        p = Path(base) / "telegram" / "ext" / "_application.py"
        if p.is_file():
            jumpa.append(p)

    # 2. venv Linux/Mac + Windows, dari akar
    for pola in (
        "installs/*/environments/*/venv/lib/python*/site-packages/telegram/ext/_application.py",
        "installs/*/environments/*/venv/Lib/site-packages/telegram/ext/_application.py",
        "*/lib/python*/site-packages/telegram/ext/_application.py",
    ):
        try:
            for p in akar.glob(pola):
                jumpa.append(p)
        except OSError:
            pass

    # 3. sandaran: rglob
    if not jumpa:
        try:
            for p in akar.rglob("site-packages/telegram/ext/_application.py"):
                jumpa.append(p)
        except OSError:
            pass

    unik = []
    for p in jumpa:
        if p not in unik:
            unik.append(p)
    return unik


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
    gd = m.groupdict()
    ind = gd.get("dind") if gd.get("dind") else (m.group("ind") + "    ")
    if not ind.strip():
        ind = m.group("ind") + "    "
    titik = m.end("doc") if gd.get("doc") else m.end("def")
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


def main() -> int:
    akar = Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/hermes"))
    print("JEJAK-MASUK: python=" + sys.executable)
    unik = calon_ptb(akar)
    print("JEJAK-MASUK: " + str(len(unik)) + " _application.py dijumpai")
    if not unik:
        print("JEJAK-MASUK: sys.path[:14] = " + repr(sys.path[:14]))
        for pola in ("installs", "."):
            d = akar / pola
            if d.is_dir():
                try:
                    isi = sorted(x.name for x in d.iterdir())[:10]
                except OSError:
                    isi = []
                print("JEJAK-MASUK: " + str(d) + " -> " + repr(isi))
        return 0
    ok = 0
    for p in unik:
        hasil = tampal(p)
        print("  " + hasil + " -> " + str(p))
        if hasil in ("PATCH OK", "sudah"):
            ok += 1
    print("JEJAK-MASUK: " + str(ok) + "/" + str(len(unik)) + " sedia")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
