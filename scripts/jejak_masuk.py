#!/usr/bin/env python3
"""jejak_masuk.py - tampal Application.process_update (titik masuk update).

MENGAPA cari melalui FAIL, bukan sys.path
========================================
Bukti (gw.log run 42414842789):
    JEJAK-MASUK: telegram/ext/_application.py tiada di sys.path
    sys.path[:12] = ['/home/.../scripts',
                     '/home/.../home/tools/python-3.14.9+.../lib/python3.14/...']
Skrip ini dijalankan sebelum site-packages venv berada dalam sys.path, jadi
carian melalui sys.path GAGAL. jejak_bot.py membuktikan carian melalui FAIL
(rglob dari HERMES_HOME) berkesan - kita guna pendekatan yang sama.

TITIK TAMPALAN
==============
  telegram/ext/_application.py : Application.process_update
  telegram/_update.py          : Update.de_json

Kalau process_update TIDAK pernah cetak apa-apa -> update tidak sampai ke app
(masalah long-poll/sesi). Kalau ia cetak tetapi handler senyap -> gate menolak.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PENANDA = "# JEJAK-MASUK-BOZ v1"

# Corak dibina daripada bahagian (tiada newline literal dalam sumber).
NL = chr(10)
Q3 = chr(34) * 3
CORAK_APP = "".join([
    "(?P<def>", NL,
    "(?P<ind>[ ", chr(92), "t]+)",
    "async def process_update", chr(92), "(", "self, update",
    "[^)]*", chr(92), ")", "[^:]*:", NL,
    ")",
    "(?P<doc>(?P<dind>[ ", chr(92), "t]*)", Q3, ".*?", Q3, NL, ")?",
])

SNIP_APP = "".join([
    "{ind}# JEJAK-MASUK-BOZ v1: cetak setiap update yang sampai ke Application.",
    NL,
    "{ind}try:", NL,
    "{ind}    print(",
    Q3.replace(chr(34), chr(34)) if False else chr(34),
    "[JEJAK-MASUK] process_update id=%s update_id=%s modul=%s",
    chr(34),
    " % (id(self), getattr(update, ", chr(34), "update_id", chr(34), ", ", chr(34), "?", chr(34),
    "), __file__), flush=True)", NL,
    "{ind}except Exception as _e:", NL,
    "{ind}    print(",
    chr(34),
    "[JEJAK-MASUK] RALAT: %r",
    chr(34),
    " % (_e,), flush=True)", NL,
])


def cari(akar: Path, nama_globs):
    jumpa = []
    try:
        for g in nama_globs:
            for p in akar.rglob(g):
                jumpa.append(p)
    except OSError:
        pass
    return jumpa


def tampal(fail: Path, corak: str, snip: str) -> str:
    try:
        teks = fail.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "BACA GAGAL: " + str(e)
    if PENANDA in teks:
        return "sudah"
    m = re.search(corak, teks, re.DOTALL)
    if not m:
        return "corak TIDAK padan"
    gd = m.groupdict()
    ind = gd.get("dind") if gd.get("dind") else (m.group("ind") + "    ")
    if not ind.strip():
        ind = m.group("ind") + "    "
    titik = m.end("doc") if gd.get("doc") else m.end("def")
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


def main() -> int:
    akar = Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/hermes"))
    kalau = [akar, Path.cwd()]
    jumpa = []
    for a in kalau:
        if a and a.exists():
            jumpa += cari(a, ["telegram/ext/_application.py"])
    unik = []
    for p in jumpa:
        if p not in unik:
            unik.append(p)
    print("JEJAK-MASUK: " + str(len(unik)) + " _application.py dijumpai")
    if not unik:
        # Diagnostik: berapa banyak pakej telegram ada, dan di mana.
        ada = cari(akar, ["telegram/__init__.py"])
        print("JEJAK-MASUK: " + str(len(ada)) + " telegram/__init__.py dijumpai")
        for p in ada[:6]:
            print("   -> " + str(p))
        return 0
    ok = 0
    for p in unik:
        hasil = tampal(p, CORAK_APP, SNIP_APP)
        print("  " + hasil + " -> " + str(p))
        if hasil in ("PATCH OK", "sudah"):
            ok += 1
    print("JEJAK-MASUK: " + str(ok) + "/" + str(len(unik)) + " sedia")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
