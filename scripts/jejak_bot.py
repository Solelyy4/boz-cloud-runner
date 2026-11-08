#!/usr/bin/env python3
"""jejak_bot.py — tampal penjejak ke adapter Telegram supaya mesej NAMPAK dalam log.

SEBAB SKRIP INI WUJUD
Gateway Hermes mencatat mesej masuk pada aras DEBUG, tetapi proses berjalan pada
aras WARNING. Jadi bot boleh menerima dan menjawab mesej sementara log KOSONG —
kita buta. Inilah yang menyebabkan "Bot TIDAK menerima sebarang mesej" dilaporkan
walaupun `pending_update_count` sentiasa 0 (ertinya gateway MEMANG mengambilnya).

CARA IA BEKERJA
Tampal satu blok pada permulaan `plugins/platforms/telegram/adapter.py` dalam
SALINAN WORKSPACE Hermes (bukan pakej asal — Hermes menyalin workspace semasa
boot). Blok itu membalut dua tempat:
  - penerimaan update  -> cetak `JEJAK MASUK  id=... dari=... teks=...`
  - penghantaran balas -> cetak `JEJAK BALAS  id=... bait=...`
Semua pada aras WARNING supaya muncul dalam `gw.log`.

Guna: python scripts/jejak_bot.py
Keluar 0 = ditampal (atau sudah ada). Keluar 1 = workspace tidak dijumpai.
"""
from __future__ import annotations

import glob
import os
import sys

PENANDA = "# --- JEJAK-BOT (dipasang oleh scripts/jejak_bot.py) ---"

BLOK = '''
# --- JEJAK-BOT (dipasang oleh scripts/jejak_bot.py) ---
# Tujuan: bukti mesej DIPROSES, bukan sekadar bot bersambung. Dua peristiwa
# penting dicatat pada aras WARNING kerana gateway berjalan pada WARNING:
#   1. update diterima daripada Telegram (id + pengirim + teks)
#   2. balasan dihantar semula (id + saiz)
# Tanpa ini, bot boleh menjawab dengan jayanya sementara log kosong, dan kita
# tersalah simpul "bot tidak menerima mesej".
import logging as _jlog
import os as _jos

_JLOG = _jlog.getLogger("JEJAK")
if not _JLOG.handlers:
    _h = _jlog.StreamHandler()
    _h.setFormatter(_jlog.Formatter("%(asctime)s JEJAK %(message)s"))
    _JLOG.addHandler(_h)
    _JLOG.setLevel(_jlog.WARNING)
    _JLOG.propagate = False

_JEJAK_LOG = _jos.environ.get("JEJAK_LOG", "")
if _JEJAK_LOG:
    try:
        _fh = _jlog.FileHandler(_JEJAK_LOG, encoding="utf-8")
        _fh.setFormatter(_jlog.Formatter("%(asctime)s JEJAK %(message)s"))
        _JLOG.addHandler(_fh)
    except Exception:
        pass


def _catat(label, a, k):
    """Catat satu peristiwa. Tidak boleh membaling — penjejak TIDAK boleh merosakkan bot."""
    try:
        mid, teks = "", ""
        for arg in a:
            if isinstance(arg, dict):
                mid = str(arg.get("update_id") or arg.get("message_id") or arg.get("chat_id") or "")
                m = arg.get("message") or arg.get("edited_message") or {}
                if isinstance(m, dict):
                    mid = mid or str(m.get("message_id") or "")
                    teks = str(m.get("text") or m.get("caption") or "")[:160]
                if not teks and isinstance(arg.get("text"), str):
                    teks = arg["text"][:160]
                break
            if isinstance(arg, str) and not teks:
                teks = arg[:160]
            # Objek PTB (Update/Message) — bukan dict. Baca atribut secara defensif.
            for attr in ("effective_message", "message"):
                o = getattr(arg, attr, None)
                if o is not None:
                    mid = mid or str(getattr(o, "message_id", "") or "")
                    teks = teks or str(getattr(o, "text", "") or getattr(o, "caption", "") or "")[:160]
                    break
            if not mid:
                mid = str(getattr(arg, "update_id", "") or "")
        _JLOG.warning("%s id=%s teks=%r", label, mid or "-", teks)
    except Exception:
        pass


def _jejak_pasang(modul):
    """Balut method modul supaya setiap panggilan dicatat. Selamat jika tiada.

    NAMA SEBENAR (dibaca daripada `_register_handlers`, bukan tekaan):
      - `_handle_text_message`  <- MessageHandler(filters.TEXT & ~COMMAND)
      - `_handle_command`       <- MessageHandler(filters.COMMAND)
      - `_on_platform_update`   <- TypeHandler(Update, group=99) catch-all
      - `send_message`          <- hantar balasan keluar
    Versi pertama meneka `_handle_update`/`_process_update`; versi kedua meneka
    `_on_platform_update` sahaja. KEDUA-DUA salah sasaran untuk mesej teks biasa,
    jadi log kekal kosong walaupun bot memproses mesej.
    """
    for nama, label in (("_handle_text_message", "MASUK"),
                        ("_handle_command", "MASUK-CMD"),
                        ("_on_platform_update", "UPDATE"),
                        ("send_message", "BALAS"),
                        ("_send_message", "BALAS")):
        asal = getattr(modul, nama, None)
        if not callable(asal) or getattr(asal, "_jejak", False):
            continue

        def buat(fn, lbl):
            import functools
            import inspect

            if inspect.iscoroutinefunction(fn):
                @functools.wraps(fn)
                async def balut(*a, **k):
                    _catat(lbl, a, k)
                    return await fn(*a, **k)
            else:
                @functools.wraps(fn)
                def balut(*a, **k):
                    _catat(lbl, a, k)
                    return fn(*a, **k)

            balut._jejak = True
            return balut

        try:
            setattr(modul, nama, buat(asal, label))
        except Exception:
            pass


try:
    import sys as _jsys
    _mod = _jsys.modules.get(__name__) or _jsys.modules.get(__name__.split(".")[0])
    _jejak_pasang(_mod)
except Exception:
    pass
# --- HUJUNG JEJAK-BOT ---
'''


def cari_adapter() -> list[str]:
    """Cari SEMUA salinan adapter.py dalam workspace Hermes."""
    home = os.environ.get("HERMES_HOME", "").strip()
    akar = []
    if home:
        akar.append(home)
    akar.append(os.path.expanduser("~/AppData/Local/hermes" if os.name == "nt" else "~/.local/share/hermes"))
    jumpa: list[str] = []
    for a in akar:
        if not os.path.isdir(a):
            continue
        for pola in ("installs/*/environments/*/workspace/plugins/platforms/telegram/adapter.py",
                     "plugins/platforms/telegram/adapter.py"):
            jumpa += glob.glob(os.path.join(a, pola))
    return sorted(set(jumpa))


def tampal(path: str) -> str:
    try:
        isi = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return f"baca gagal: {e}"
    if PENANDA in isi:
        return "sudah ada"
    # Sisip SELEPAS docstring/import permulaan supaya tidak merosakkan modul.
    # Guna strategi selamat: letak blok di HUJUNG fail — modul sudah dimuatkan
    # sepenuhnya ketika itu, jadi getattr melihat semua fungsi yang wujud.
    baru = isi.rstrip() + "\n\n" + BLOK + "\n"
    try:
        open(path, "w", encoding="utf-8", newline="\n").write(baru)
    except Exception as e:
        return f"tulis gagal: {e}"
    # Sahkan baca-balik
    semula = open(path, encoding="utf-8", errors="replace").read()
    if PENANDA not in semula:
        return "PENGESAHAN GAGAL"
    return "ditampal"


def main() -> int:
    calon = cari_adapter()
    if not calon:
        print("JEJAK: workspace Hermes tidak dijumpai — penjejak TIDAK dipasang")
        print("JEJAK: (ini normal jika gateway belum boot kali pertama)")
        return 1
    for p in calon:
        hasil = tampal(p)
        print(f"JEJAK {hasil}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
