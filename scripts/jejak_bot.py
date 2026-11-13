#!/usr/bin/env python3
"""jejak_bot.py — tampal penjejak ke adapter Telegram supaya mesej NAMPAK dalam log.

SEBAB SKRIP INI WUJUD
Gateway mencatat mesej masuk pada aras DEBUG tetapi proses berjalan pada WARNING,
jadi bot boleh menerima dan menjawab sementara log KOSONG. Itulah yang membuat kita
berjam-jam menyangka "bot tidak menerima mesej" sedangkan `pending` sentiasa 0.

DUA PEPIJAT SEBENAR YANG DISELESAIKAN DI SINI
---------------------------------------------
1. Membalut MODUL tidak menyentuh method kelas — method tinggal dalam
   `TelegramAdapter`. Versi lama berbuat begitu lalu "dipasang" tanpa kesan.

2. LEBIH HALUS: `_register_handlers` mendaftar
       app.add_handler(MessageHandler(..., self._handle_text_message))
   Rujukan `self._handle_text_message` DIKUNCI pada saat pendaftaran. Membalut
   atribut kelas SELEPAS itu tidak mengubah fungsi yang sudah dirujuk PTB — jadi
   pembalutan nampak "berjaya" tetapi penjejak tidak pernah dipanggil.
   (Tanda tangan dalam log: `DIPASANG ... 3 method dibalut` tetapi TIADA `JEJAK MASUK`.)

PENYELESAIAN
------------
Suntik penjejak TERUS ke dalam BADAN dua method (bukan membalut):
  - `_handle_text_message` -> cetak peristiwa masuk
  - `send_message`         -> cetak peristiwa balas
Tambah satu baris bukti pada `_register_handlers` supaya kita tahu handler didaftar.

Guna: python scripts/jejak_bot.py
Keluar 0 = ditampal (atau sudah ada). Keluar 1 = workspace tidak dijumpai.
"""
from __future__ import annotations

import glob
import os
import sys

PENANDA = "# --- JEJAK-BOT (dipasang oleh scripts/jejak_bot.py) ---"

# Suntikan baris masuk — diletak sebagai baris PERTAMA badan method.
SUNTIK_MASUK = '''        try:
            import logging as _jl, os as _jo
            _ju = update
            _jm = getattr(_ju, "effective_message", None) or getattr(_ju, "message", None)
            _jid = getattr(_ju, "update_id", "?")
            _jmid = getattr(_jm, "message_id", "?") if _jm is not None else "?"
            _jt = (getattr(_jm, "text", None) or getattr(_jm, "caption", None)) if _jm is not None else None
            _jf = getattr(_jm, "from_user", None) if _jm is not None else None
            _jc = getattr(getattr(_jm, "chat", None), "id", "?") if _jm is not None else "?"
            _jd = (getattr(_jf, "username", None) or getattr(_jf, "first_name", None) or "?") if _jf is not None else "?"
            _jn = "JEJAK MASUK update=%s msg=%s chat=%s dari=%s teks=%r" % (
                _jid, _jmid, _jc, _jd, (str(_jt)[:160] if _jt is not None else None))
            _jl.getLogger("JEJAK").warning(_jn)
            _jp = _jo.path.join(_jo.environ.get("GITHUB_WORKSPACE", "."), "gw_trace.log")
            with _jo.open(_jp, "a", encoding="utf-8") as _jfh:
                _jfh.write(_jn + "\\n")
        except Exception:
            pass
'''

# Suntikan baris balas — diletak sebagai baris PERTAMA badan `send_message`.
SUNTIK_BALAS = '''        try:
            import logging as _jl, os as _jo
            _jn = "JEJAK BALAS chat=%s" % (locals().get("chat_id", "?"),)
            _jl.getLogger("JEJAK").warning(_jn)
            _jp = _jo.path.join(_jo.environ.get("GITHUB_WORKSPACE", "."), "gw_trace.log")
            with _jo.open(_jp, "a", encoding="utf-8") as _jfh:
                _jfh.write(_jn + "\\n")
        except Exception:
            pass
'''

SUNTIK_DAFTAR = '''        try:
            import logging as _jl, os as _jo
            _jl.getLogger("JEJAK").warning("JEJAK DAFTAR handler teks didaftar")
            _jp = _jo.path.join(_jo.environ.get("GITHUB_WORKSPACE", "."), "gw_trace.log")
            with _jo.open(_jp, "a", encoding="utf-8") as _jfh:
                _jfh.write("JEJAK DAFTAR handler teks didaftar\\n")
        except Exception:
            pass
'''


def cari_adapter() -> list[str]:
    """Cari SEMUA salinan adapter.py dalam workspace Hermes."""
    home = os.environ.get("HERMES_HOME", "").strip()
    akar = []
    if home:
        akar.append(home)
    akar.append(os.path.expanduser(
        "~/AppData/Local/hermes" if os.name == "nt" else "~/.local/share/hermes"))
    jumpa: list[str] = []
    for a in akar:
        if not os.path.isdir(a):
            continue
        for pola in ("installs/*/environments/*/workspace/plugins/platforms/telegram/adapter.py",
                     "plugins/platforms/telegram/adapter.py"):
            jumpa += glob.glob(os.path.join(a, pola))
    return sorted(set(jumpa))


def _sisip_badan(teks: str, tandatangan: str, suntik: str) -> tuple[str, bool]:
    """Sisip `suntik` sebagai baris pertama BADAN method bertandatangan `tandatangan`."""
    i = teks.find(tandatangan)
    if i < 0:
        return teks, False
    j = teks.find("\n", i)
    if j < 0:
        return teks, False
    return teks[:j + 1] + suntik + teks[j + 1:], True


def tampal(path: str) -> str:
    try:
        isi = open(path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return f"baca gagal: {e}"
    if "JEJAK MASUK" in isi and "JEJAK BALAS" in isi:
        return "sudah ada"

    teks = isi
    ok_m = ok_b = ok_d = False
    # Tandatangan SEBENAR (dibaca daripada adapter.py, bukan tekaan):
    #   async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    import re as _re
    m = _re.search(r"^    async def _handle_text_message\(.*?:$", teks, _re.M | _re.S)
    if m:
        teks = teks[:m.end()] + "\n" + SUNTIK_MASUK + teks[m.end() + 1:]
        ok_m = True
    m = _re.search(r"^    async def send\(.*?:$", teks, _re.M | _re.S)
    if m:
        teks = teks[:m.end()] + "\n" + SUNTIK_BALAS + teks[m.end() + 1:]
        ok_b = True
    # BUKTI 13 Nov 2026: corak lama tidak padan kerana kod sebenar berakhir dengan "))"
    # (add_handler(TelegramMessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_message)))
    # Akibatnya daftar=False -> penjejak TIDAK dipasang pada pendaftaran handler, jadi
    # kita buta tentang sama ada handler benar-benar didaftarkan. Corak baharu tahan variasi.
    m = _re.search(
        r"^(\s*)app\.add_handler\(\s*TelegramMessageHandler\(\s*filters\.TEXT[^\n]*?\)\s*\)\s*$",
        teks, _re.M)
    if m:
        teks = teks[:m.end()] + "\n" + SUNTIK_DAFTAR + teks[m.end() + 1:]
        ok_d = True

    if not ok_m:
        return "GAGAL: method _handle_text_message tidak dijumpai"
    if not ok_b:
        return "GAGAL: method send_message tidak dijumpai"

    if PENANDA not in teks:
        teks = teks.rstrip("\n") + "\n" + PENANDA + "\n"
    try:
        open(path, "w", encoding="utf-8", newline="\n").write(teks)
    except Exception as e:
        return f"tulis gagal: {e}"
    semula = open(path, encoding="utf-8", errors="replace").read()
    if "JEJAK MASUK" not in semula or "JEJAK BALAS" not in semula:
        return "PENGESAHAN GAGAL"
    return f"ditampal (masuk={ok_m} balas={ok_b} daftar={ok_d})"


def main() -> int:
    calon = cari_adapter()
    if not calon:
        print("JEJAK: workspace Hermes tidak dijumpai — penjejak TIDAK dipasang")
        print("JEJAK: (ini normal jika gateway belum boot kali pertama)")
        return 1
    for p in calon:
        print(f"JEJAK {tampal(p)}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
