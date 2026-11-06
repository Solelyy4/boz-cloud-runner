#!/usr/bin/env python3
"""jejak_bot.py — patch jejak mesej masuk ke log bot (aras WARNING).

MENGAPA
=======
Bukti 2026-11-06 (status.log run 42233774433, baris 21):
    denyut tick=15 fd=30/65536
Bot HIDUP dan SIHAT (fd hanya 30/65536, tiada kebocoran), tetapi gw.log TIDAK
menunjukkan sebarang pemprosesan mesej. Punca: adapter Telegram mencatat mesej
masuk pada aras `logger.debug`, manakala gateway berjalan pada aras WARNING.
Jadi pemprosesan berlaku TETAPI TIDAK KELIHATAN — mustahil membuktikan bot
berfungsi atau tidak.

Skrip ini menampal `_handle_text_message` (dan handler command/media) supaya
setiap mesej masuk ditulis pada aras WARNING. Ia idempoten dan UNDUR sendiri
jika patch menghasilkan sintaks rosak — bot tidak pernah dibiarkan rosak.

Guna:
    HERMES_SRC=<dir hermes-agent> python scripts/jejak_bot.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PENANDA = "# JEJAK-BOT-BOZ v1"

# Handler yang kita tampal -> nama jenis mesej.
HANDLER = {
    "_handle_text_message": "TEKS",
    "_handle_command": "PERINTAH",
    "_handle_media_message": "MEDIA",
}

SNIP_TEMPLATE = '''{ind}# JEJAK-BOT-BOZ v1: catat mesej masuk pada aras WARNING supaya
{ind}# ia kelihatan dalam gw.log (bukti bot MEMPROSES, bukan hanya sambung).
{ind}try:
{ind}    _jb_m = self._effective_update_message(update)
{ind}    _jb_teks = (getattr(_jb_m, "text", None) or getattr(_jb_m, "caption", None) or "")
{ind}    logger.warning("[JEJAK] MESEJ {jenis} MASUK dari %s: %s",
{ind}                   getattr(getattr(update, "effective_user", None), "id", "?"),
{ind}                   str(_jb_teks)[:200])
{ind}except Exception:
{ind}    pass
'''


def cari_adapter(akar: Path) -> Path | None:
    """Cari adapter.py Telegram dalam pepohon akar."""
    try:
        for p in akar.rglob("plugins/platforms/telegram/adapter.py"):
            return p
    except OSError:
        return None
    return None


def tampal_handler(teks: str, nama: str, jenis: str) -> tuple[str, bool]:
    """Tampal jejak selepas definisi + docstring handler `nama`.

    PENTING: indent untuk sisipan ialah indent BADAN handler (8 ruang), bukan
    indent `def` (4). Menggunakan indent `def` menyebabkan jejak ditulis di aras
    fungsi (bukan dalamnya) -> SyntaxError 'await outside function'. Kes ini
    disahkan pada ujian 2026-11-06; skrip undur dengan selamat.
    """
    corak = re.compile(
        rf"(?P<def>\n(?P<ind>[ \t]+)async def {re.escape(nama)}\([^)]*\)[^:]*:\n)"
        r"(?P<doc>(?P<dind>[ \t]*)\"\"\".*?\"\"\"\n)?",
        re.DOTALL,
    )
    m = corak.search(teks)
    if not m:
        return teks, False
    # Indent badan = indent def + 4; kalau ada docstring, guna indent docstring.
    ind = (m.group("dind") if m.group("dind") else m.group("ind") + "    ")
    if not ind.strip():
        ind = m.group("ind") + "    "
    sisip = SNIP_TEMPLATE.format(ind=ind, jenis=jenis)
    titik = m.end("doc") if m.group("doc") else m.end("def")
    return teks[:titik] + sisip + teks[titik:], True


def main() -> int:
    src = os.environ.get("HERMES_SRC", "")
    calon: list[Path] = []
    if src:
        calon.append(Path(src))
    calon += [Path.cwd(), Path.home() / ".local/share/hermes",
              Path("/home/runner/work"), Path.home()]
    adapter: Path | None = None
    for c in calon:
        if c and c.exists():
            adapter = cari_adapter(c)
            if adapter:
                break
    if not adapter:
        print("JEJAK: adapter.py tidak dijumpai — langkau (bukan ralat maut)")
        return 0
    print(f"JEJAK: adapter -> {adapter}")
    teks = adapter.read_text(encoding="utf-8", errors="replace")
    if PENANDA in teks:
        print("JEJAK: sudah ditampal (idempoten) — tiada perubahan")
        return 0

    asal = teks
    ditampal: list[str] = []
    for nama, jenis in HANDLER.items():
        teks, ok = tampal_handler(teks, nama, jenis)
        if ok:
            ditampal.append(nama)
    if not ditampal:
        print("JEJAK: tiada handler sepadan — bot tidak diubah (tetap berfungsi)")
        return 0

    # Sahkan boleh dikompil; undur jika rosak.
    try:
        compile(teks, str(adapter), "exec")
    except SyntaxError as e:
        print(f"JEJAK: sintaks rosak ({e}) — DIUNDUR, bot tidak diubah")
        return 0

    simpan = adapter.with_suffix(".py.jejak_asli")
    if not simpan.exists():
        simpan.write_text(asal, encoding="utf-8")
    adapter.write_text(teks, encoding="utf-8")
    print(f"JEJAK: patch BERJAYA pada {len(ditampal)} handler: {', '.join(ditampal)}")
    print("JEJAK: sintaks sah — setiap mesej masuk akan dicatat [JEJAK] dalam gw.log")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
