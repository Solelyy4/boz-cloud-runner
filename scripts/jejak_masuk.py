#!/usr/bin/env python3
"""jejak_masuk.py - tampal Application.process_update supaya setiap update yang
sampai ke python-telegram-bot dicetak.

PENDEKATAN TEPAT (tidak boleh tersasar)
=======================================
Versi sebelum ini meneka laluan PTB melalui glob venv/lib/python*/site-packages
dan GAGAL (0 dijumpai) walaupun venv betul. Bukti gw_trace 42419122082:
    python=.../installs/.../venv/bin/python
    JEJAK-MASUK: 0 _application.py dijumpai

Versi ini IMPORT python-telegram-bot dan bertanya kepadanya DI MANA ia tinggal:
    import telegram
    telegram.__file__  ->  .../site-packages/telegram/__init__.py
Laluan itu kita pakai untuk mencari ext/_application.py. Mustahil tersasar kerana
kita guna laluan yang Python sendiri laporkan.

Nota: skrip ini mesti dijalankan dengan python venv gateway ($GWPY), yang memang
mempunyai PTB (gw.log: "telegram OK 22.8").
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
    print("JEJAK-MASUK: python=" + sys.executable)
    try:
        import telegram  # noqa: PLC0415
    except Exception as e:
        print("JEJAK-MASUK: GAGAL import telegram: %r" % (e,))
        return 0
    print("JEJAK-MASUK: telegram " + getattr(telegram, "__version__", "?") +
          " -> " + str(telegram.__file__))
    pakej = Path(telegram.__file__).parent
    calon = [pakej / "ext" / "_application.py", pakej / "_update.py"]
    ada = [p for p in calon if p.is_file()]
    print("JEJAK-MASUK: " + str(len(ada)) + "/" + str(len(calon)) + " fail PTB dijumpai")
    if not ada:
        try:
            isi = sorted(x.name for x in (pakej / "ext").iterdir())[:14]
        except OSError:
            isi = []
        print("JEJAK-MASUK: " + str(pakej / "ext") + " -> " + repr(isi))
        return 0
    for p in ada:
        print("  " + tampal(p) + " -> " + str(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
