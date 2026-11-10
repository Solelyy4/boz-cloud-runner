#!/usr/bin/env python3
"""jangan_buang.py — halang gateway MEMBUANG mesej BOZ semasa pulih daripada konflik.

PEPIJAT SEBENAR (berjam-jam hilang, mesej tidak pernah sampai)
=============================================================
Adapter Telegram Hermes memanggil `_start_polling_once(..., drop_pending_updates=True)`
DI DUA tempat, terutamanya dalam `_handle_polling_conflict`:

    await self._start_polling_once(app, drop_pending_updates=True, ...)

Komen dalam kod itu sendiri menerangkan tujuan: `drop_pending_updates=True` memaksa
Telegram MENAMATKAN sesi getUpdates lain (zombi atau percubaan sendiri yang lewat).

MASALAHNYA: parameter yang sama juga memberitahu Telegram untuk **MEMBUANG SEMUA
UPDATE YANG SEDANG MENUNGGU**. Jadi setiap kali gateway memulihkan diri daripada
konflik 409, ia membuang mesej BOZ yang belum diproses.

Kesan yang kita lihat (dan salah tafsir berulang kali):
    - `pending_update_count` sentiasa 0      -> nampak "sihat"
    - `Connected to Telegram (polling mode)` -> nampak "bersambung"
    - `getMe 200`                            -> nampak "hidup"
    - tetapi TIADA mesej sampai ke handler, selama-lamanya

Kita mengejar rangkaian, token, proxy, dua-pertindihan-bot, parser SSE, penjejak
yang tidak dipasang... sedangkan punca sebenar ialah satu parameter boolean yang
membuang kerja BOZ tanpa jejak.

PEMBETULAN
==========
Tukar `drop_pending_updates=True` -> `drop_pending_updates=False` pada pemulihan
konflik. Konflik masih diselesaikan (Telegram tetap menamatkan sesi lama apabila
klien baharu mula long-poll), tetapi update yang menunggu TIDAK dibuang — ia
diproses apabila gateway bersambung semula.

Guna: python scripts/jangan_buang.py
Keluar 0 = ditampal / sudah ada. Keluar 1 = workspace tiada.
"""
from __future__ import annotations

import glob
import os
import re
import sys

PENANDA = "# JANGAN-BUANG-BOZ v1"
# Diukur 11 Nov 2026: corak tunggal yang tepat ("await self._start_polling_once(app,
# drop_pending_updates=True") melaporkan "corak TIDAK padan (0 tempat)" di runner
# walaupun kod itu jelas wujud dalam adapter.py. Sebabnya: setiap keluaran Hermes
# mengubah indentasi/pembalutan baris, dan `str.replace` tidak tahan perubahan itu.
# Akibatnya tampalan GAGAL SENYAP, `drop_pending_updates=True` kekal, dan setiap kali
# gateway pulih daripada konflik 409 ia MEMBUANG mesej BOZ yang menunggu.
# Gejala menipu: `pending_update_count` kekal 0 dan log nampak sihat sepenuhnya.
#
# Sekarang: padan REGEX yang tahan indentasi dan berbilang baris, betulkan SETIAP
# tempat, dan sahkan bilangan penukaran. Kegagalan mesti KETARA, bukan senyap.
POLA = re.compile(
    r"(_start_polling_once\s*\(\s*[^()]*?drop_pending_updates\s*=\s*)True",
    re.S,
)


def cari_adapter() -> list[str]:
    home = os.environ.get("HERMES_HOME", "").strip()
    akar = [home] if home else []
    akar.append(os.path.expanduser(
        "~/AppData/Local/hermes" if os.name == "nt" else "~/.local/share/hermes"))
    jumpa: set[str] = set()
    for a in akar:
        if not os.path.isdir(a):
            continue
        for pola in ("installs/*/environments/*/workspace/plugins/platforms/telegram/adapter.py",
                     "plugins/platforms/telegram/adapter.py"):
            jumpa.update(os.path.abspath(p) for p in glob.glob(os.path.join(a, pola)))
    return sorted(jumpa)


def tampal(path: str) -> str:
    try:
        teks = open(path, encoding="utf-8", errors="replace").read()
    except OSError as e:
        return f"BACA GAGAL: {e}"
    n = len(POLA.findall(teks))
    if n == 0:
        if PENANDA in teks:
            return "sudah ditampal"
        # 0 padanan boleh bermakna DUA perkara berbeza. Bezakan supaya operator
        # tidak panik (atau terlepas pandang) bila membaca log:
        #   - tiada lagi `drop_pending_updates=True` dalam KOD -> sudah selamat
        #   - masih ada rujukan tetapi corak tak padan     -> skrip perlu dikemas kini
        kod_masih_true = [
            b for b in teks.splitlines()
            if "drop_pending_updates=True" in b and not b.lstrip().startswith("#")
        ]
        if not kod_masih_true:
            return "selamat: tiada lagi drop_pending_updates=True dalam kod"
        return (f"corak TIDAK padan: {len(kod_masih_true)} tempat KOD masih "
                f"drop_pending_updates=True - skrip perlu dikemas kini untuk versi Hermes ini")
    baru = POLA.sub(r"\1False", teks)
    # Jangan sekali-kali menulis fail yang tidak boleh dikompil — adapter rosak =
    # gateway mati sepenuhnya, jauh lebih buruk daripada mesej hilang.
    try:
        compile(baru, path, "exec")
    except SyntaxError as e:
        return f"sintaks rosak ({e}) - DIUNDUR"
    simpan = path + ".jangan_buang_asli"
    if not os.path.exists(simpan):
        try:
            open(simpan, "w", encoding="utf-8", newline="\n").write(teks)
        except OSError:
            pass
    # Tulis PENANDA supaya penjalanan berikutnya kenal "sudah ditampal" dan tidak
    # menulis semula fail yang sama berulang kali.
    if PENANDA not in baru:
        baru = baru.rstrip("\n") + "\n" + PENANDA + "\n"
    try:
        open(path, "w", encoding="utf-8", newline="\n").write(baru)
    except OSError as e:
        return f"TULIS GAGAL: {e}"
    # Buang cache .pyc lama supaya Python memuat semula fail yang ditampal.
    d = os.path.dirname(path)
    cache = os.path.join(d, "__pycache__")
    if os.path.isdir(cache):
        for f in glob.glob(os.path.join(cache, "adapter*.pyc")):
            try:
                os.unlink(f)
            except OSError:
                pass
    return f"ditampal {n} tempat"


def main() -> int:
    def c(m: str) -> None:
        print(m, flush=True)

    calon = cari_adapter()
    if not calon:
        c("JANGAN-BUANG: workspace Hermes tidak dijumpai — tiada tampalan")
        return 1
    c(f"JANGAN-BUANG: {len(calon)} adapter dijumpai")
    for p in calon:
        c(f"  {tampal(p)} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
