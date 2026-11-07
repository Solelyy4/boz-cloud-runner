#!/usr/bin/env python3
"""jejak_bot.py - patch jejak mesej masuk ke log bot.

MENGAPA print(), BUKAN logger.warning
=====================================
Versi sebelum ini guna logger.warning. Patch dilaporkan "BERJAYA pada 3 handler"
dan kedua-dua salinan adapter.py (hermes-agent + workspace) mengandungi penanda,
tetapi TIADA baris [JEJAK] muncul dalam gw.log — walaupun log WARNING adapter
yang lain muncul ("[Telegram] Connected to Telegram").

Punca paling mungkin: `logger` modul adapter tidak mengalir ke gw.log pada aras
WARNING semasa gateway berjalan (konfigurasi logging mengalihkan handler), ATAU
update tidak sampai ke handler langsung (gate lebih awal).

Penyelesaian: print(..., flush=True). gw.log ditulis sebagai `>> gw.log 2>&1`
daripada stdout proses gateway, jadi print TIDAK BOLEH ditapis. Kita juga:
  * cetak __file__ modul (sahkan salinan MANA yang dimuat)
  * cetak pengecualian sebenar (jangan telan)
  * tampal pada KETIGA handler + pada titik masuk update

Bukti saiz berbeza (laptop 7 Nov 2026) yang membuktikan salinan berasingan:
    hermes-agent/plugins/platforms/telegram/adapter.py            441,748 bait
    installs/.../workspace/plugins/platforms/telegram/adapter.py  442,334 bait
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PENANDA = "# JEJAK-BOT-BOZ v1"

HANDLER = {
    "_handle_text_message": "TEKS",
    "_handle_command": "PERINTAH",
    "_handle_media_message": "MEDIA",
    "_handle_sticker": "STIKER",
    "_handle_location_message": "LOKASI",
}

SNIP_TEMPLATE = """{ind}# JEJAK-BOT-BOZ v1: print() TIDAK BOLEH ditapis oleh konfigurasi
{ind}# logging, tidak seperti logger.warning. gw.log = stdout gateway (>> gw.log 2>&1).
{ind}try:
{ind}    _jb_m = self._effective_update_message(update)
{ind}    _jb_teks = (getattr(_jb_m, "text", None) or getattr(_jb_m, "caption", None) or "")
{ind}    print("[JEJAK] MESEJ {jenis} MASUK dari %s: %s | modul=%s" % (
{ind}        getattr(getattr(update, "effective_user", None), "id", "?"),
{ind}        str(_jb_teks)[:180], __file__), flush=True)
{ind}except Exception as _jb_e:
{ind}    print("[JEJAK] RALAT dalam jejak {jenis}: %r" % (_jb_e,), flush=True)
"""


def tampal_handler(teks: str, nama: str, jenis: str):
    corak = re.compile(
        rf"(?P<def>\n(?P<ind>[ \t]+)async def {re.escape(nama)}\([^)]*\)[^:]*:\n)"
        r"(?P<doc>(?P<dind>[ \t]*)\"\"\".*?\"\"\"\n)?",
        re.DOTALL,
    )
    m = corak.search(teks)
    if not m:
        return teks, False
    ind = (m.group("dind") if m.group("dind") else m.group("ind") + "    ")
    if not ind.strip():
        ind = m.group("ind") + "    "
    sisip = SNIP_TEMPLATE.format(ind=ind, jenis=jenis)
    titik = m.end("doc") if m.group("doc") else m.end("def")
    return teks[:titik] + sisip + teks[titik:], True


def cari_semua_adapter(akar: Path):
    jumpa = []
    try:
        for p in akar.rglob("plugins/platforms/telegram/adapter.py"):
            jumpa.append(p)
    except OSError:
        pass
    return jumpa


def tampal_satu(adapter: Path) -> str:
    try:
        teks = adapter.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "BACA GAGAL: " + str(e)
    if PENANDA in teks:
        # Kalau penanda LAMA (logger.warning) ada, ia sudah ditampal versi lama.
        # Kita tidak boleh campur; nyah versi lama dahulu jika ada .jejak_asli.
        simpan = adapter.with_suffix(".py.jejak_asli")
        if simpan.exists() and "logger.warning(\"[JEJAK]" in teks:
            try:
                adapter.write_text(simpan.read_text(encoding="utf-8", errors="replace"),
                                   encoding="utf-8")
                teks = adapter.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                return "NYAH VERSI LAMA GAGAL: " + str(e)
        else:
            return "sudah ditampal (idempoten)"
    asal = teks
    ditampal = []
    for nama, jenis in HANDLER.items():
        teks, ok = tampal_handler(teks, nama, jenis)
        if ok:
            ditampal.append(nama)
    if not ditampal:
        return "tiada handler sepadan"
    try:
        compile(teks, str(adapter), "exec")
    except SyntaxError as e:
        return "sintaks rosak (" + str(e) + ") - DIUNDUR"
    simpan = adapter.with_suffix(".py.jejak_asli")
    if not simpan.exists():
        try:
            simpan.write_text(asal, encoding="utf-8")
        except OSError:
            pass
    try:
        adapter.write_text(teks, encoding="utf-8")
    except OSError as e:
        return "TULIS GAGAL: " + str(e)
    # Buang __pycache__ berhampiran supaya Python TIDAK guna .pyc lama.
    import shutil
    cache = adapter.parent / "__pycache__"
    if cache.is_dir():
        for f in cache.glob("adapter*.pyc"):
            try:
                f.unlink()
            except OSError:
                pass
    return "PATCH OK (" + str(len(ditampal)) + "): " + ", ".join(ditampal)


def main() -> int:
    akar = Path(os.environ.get("HERMES_HOME") or os.path.expanduser("~/hermes"))
    kalau = [akar, Path.cwd(), Path.home() / ".local/share/hermes"]
    semua = []
    for a in kalau:
        if a and a.exists():
            semua += cari_semua_adapter(a)
    unik = []
    for p in semua:
        if p not in unik:
            unik.append(p)
    if not unik:
        print("JEJAK: adapter.py tidak dijumpai - langkau (bukan ralat maut)")
        return 0
    print("JEJAK: " + str(len(unik)) + " salinan adapter.py dijumpai")
    ok = 0
    for i, p in enumerate(unik, 1):
        hasil = tampal_satu(p)
        print("  [" + str(i) + "] " + hasil + " -> " + str(p))
        if hasil.startswith("PATCH OK") or hasil.startswith("sudah"):
            ok += 1
    print("JEJAK: " + str(ok) + "/" + str(len(unik)) + " salinan sedia untuk dimuat gateway")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
