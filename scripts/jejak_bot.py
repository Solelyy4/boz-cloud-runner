#!/usr/bin/env python3
"""jejak_bot.py - patch jejak mesej masuk ke log bot (aras WARNING).

MENGAPA
=======
Adapter Telegram mencatat mesej masuk pada aras `debug`, manakala gateway
berjalan pada aras WARNING. Jadi pemprosesan berlaku TETAPI TIDAK KELIHATAN -
mustahil membuktikan bot berfungsi atau tidak.

PUNCA PATCH SEBELUM INI GAGAL (dibuktikan 7 Nov 2026)
=====================================================
Versi lama hanya menampal SATU fail:
    <HERMES_HOME>/hermes-agent/plugins/platforms/telegram/adapter.py
Tetapi Hermes menyalin (bukan symlink) pokok plugin ke
    <HERMES_HOME>/installs/<id>/environments/<env>/workspace/plugins
dan gateway mengimport dari SALINAN itu - nama modul dibina daripada
manifest_key: "plugins/platforms/telegram" menjadi "plugins__platforms__telegram"
(bukti gw_trace.log run 42396007028: hermes_plugins.platforms__telegram.adapter).

Bukti saiz berbeza pada laptop:
    hermes-agent/plugins/platforms/telegram/adapter.py            441,748 bait
    installs/.../workspace/plugins/platforms/telegram/adapter.py  442,334 bait

Versi ini menampal SETIAP salinan yang dijumpai. Idempoten; undur sendiri jika
patch menghasilkan sintaks rosak - bot tidak pernah dibiarkan rosak.
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
}

SNIP_TEMPLATE = """{ind}# JEJAK-BOT-BOZ v1: catat mesej masuk pada aras WARNING supaya
{ind}# ia kelihatan dalam gw.log (bukti bot MEMPROSES, bukan hanya sambung).
{ind}try:
{ind}    _jb_m = self._effective_update_message(update)
{ind}    _jb_teks = (getattr(_jb_m, "text", None) or getattr(_jb_m, "caption", None) or "")
{ind}    logger.warning("[JEJAK] MESEJ {jenis} MASUK dari %s: %s",
{ind}                   getattr(getattr(update, "effective_user", None), "id", "?"),
{ind}                   str(_jb_teks)[:200])
{ind}except Exception:
{ind}    pass
"""


def tampal_handler(teks: str, nama: str, jenis: str):
    """Tampal jejak selepas definisi + docstring handler."""
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
    """Cari SETIAP adapter.py Telegram di bawah akar, termasuk salinan di dalam
    installs/*/environments/*/workspace (yang sebenarnya dimuat oleh gateway)."""
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
