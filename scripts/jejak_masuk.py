#!/usr/bin/env python3
"""jejak_masuk.py - tampal Application.process_update untuk jejak update.

VERSI 5 - TANPA REGEX
=====================
Versi 4 gagal dengan:
    re.PatternError: missing ), unterminated subpattern at position 77 (line 3, column 2)
Regex kompleks yang dibina melalui gabungan rentetan (chr(92)+"t" untuk TAB, kurungan
bersarang untuk docstring opsional) terlalu rapuh. Carian teks lurus lebih selamat dan
cukup untuk kes ini.

LALUAN PTB
==========
Versi 3 gagal dengan ModuleNotFoundError kerana ia dijalankan SEBELUM PTB dipasang.
Kini blok ini berada SELEPAS `pip install python-telegram-bot`. Versi ini juga tidak
meneka laluan: ia `import telegram` dan guna `telegram.__file__`.

Bukti (gw_trace.log run 42423444372):
    JEJAK-MASUK: telegram 22.8 -> .../venv/lib/python3.14/site-packages/telegram/__init__.py
    JEJAK-MASUK: 2/2 fail PTB dijumpai
    re.PatternError: missing ), unterminated subpattern at position 77
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

PENANDA = "# JEJAK-MASUK-BOZ v1"


def _masa() -> str:
    """Cap waktu UTC untuk diari — tanpa ini, log berbilang run tidak boleh dibezakan."""
    import datetime  # noqa: PLC0415

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

NL = chr(10)
Q3 = chr(34) * 3
BS = chr(92)
TAB = BS + "t"

# Header lurus - tiada regex.
# PEPIJAT: versi lama cari "async def process_update(self, update: Update, context: CallbackContext"
# tetapi PTB 22.8 menukar tandatangan kepada `(self, update: object) -> None` (tiada `context`).
# Akibatnya carian gagal senyap ("corak TIDAK padan") dan penjejak tidak pernah dipasang —
# kita terus buta terhadap mesej masuk walaupun gateway sihat.
# Kini kita cari PREFIX pendek yang stabil merentas versi PTB.
HEADER = "async def process_update(self, update:"

SNIP = (
    "{ind}# JEJAK-MASUK-BOZ v1: cetak setiap update yang sampai ke Application."
    + NL
    + "{ind}try:"
    + NL
    + "{ind}    print("
    + chr(34)
    + "[JEJAK-MASUK] process_update id=%s update_id=%s"
    + chr(34)
    + " % (id(self), getattr(update, "
    + chr(34) + "update_id" + chr(34) + ", " + chr(34) + "?" + chr(34) + ")), flush=True)"
    + NL
    + "{ind}except Exception as _e:"
    + NL
    + "{ind}    print(" + chr(34) + "[JEJAK-MASUK] RALAT: %r" + chr(34) + " % (_e,), flush=True)"
    + NL
)


def garis_indent(teks: str, pos: int) -> str:
    """Indentasi baris yang mengandungi pos."""
    mula = teks.rfind(NL, 0, pos) + 1
    ind = ""
    for c in teks[mula:]:
        if c in (" ", TAB):
            ind += c
        else:
            break
    return ind or "        "


def titik_sisip(teks: str, kepala: int) -> int:
    """Hujung baris 'def' (selepas ':'), melepasi docstring kalau ada."""
    nl = teks.find(NL, kepala)
    if nl < 0:
        return -1
    titik = nl + 1
    # lompat docstring penutup kalau ada
    sisa = teks[titik:titik + 600]
    strip = sisa.lstrip(" " + TAB)
    if strip.startswith(Q3):
        ofs = len(sisa) - len(strip)
        j = titik + ofs + 3
        j2 = teks.find(Q3, j)
        if j2 > 0:
            nl2 = teks.find(NL, j2)
            if nl2 > 0:
                titik = nl2 + 1
    return titik


def tampal(fail: Path) -> str:
    try:
        teks = fail.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return "BACA GAGAL: " + str(e)
    if PENANDA in teks:
        return "sudah"
    kepala = teks.find(HEADER)
    if kepala < 0:
        return "corak TIDAK padan"
    titik = titik_sisip(teks, kepala)
    if titik < 0:
        return "corak TIDAK padan (tiada baris)"
    ind = garis_indent(teks, kepala) + "    "
    baru = teks[:titik] + SNIP.format(ind=ind) + teks[titik:]
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
    # Output di-flush secara eksplisit: di runner, stdout Python dibuffer dan baris
    # penting boleh hilang apabila proses induk keluar — kita pernah buta tentang
    # sebab penampal gagal hanya kerana mesejnya tidak sempat dicetak.
    #
    # TAMBAHAN: tulis juga ke FAIL di sebelah skrip. `tee` boleh memotong baris
    # apabila proses induk keluar, dan kita sudah berulang kali kehilangan bukti
    # penting (baris "PATCH OK" hilang walaupun tampalan berjaya di tempatan).
    diari = Path(__file__).with_name("jejak_masuk.log")

    def c(m: str) -> None:
        print(m, flush=True)
        try:
            with diari.open("a", encoding="utf-8") as f:
                f.write(m + "\n")
        except OSError:
            pass

    c("=== " + _masa() + " mula ===")
    c("JEJAK-MASUK: python=" + sys.executable)
    try:
        import telegram  # noqa: PLC0415
    except Exception as e:
        c("JEJAK-MASUK: GAGAL import telegram: %r" % (e,))
        return 0
    c("JEJAK-MASUK: telegram " + getattr(telegram, "__version__", "?") +
      " -> " + str(telegram.__file__))
    pakej = Path(telegram.__file__).parent
    calon = [pakej / "ext" / "_application.py"]
    if not calon[0].is_file():
        try:
            calon = sorted((pakej / "ext").glob("_*.py"))
        except OSError:
            calon = []
    c("JEJAK-MASUK: " + str(len(calon)) + " fail PTB dijumpai")
    for p in calon:
        hasil = tampal(p)
        c("  " + hasil + " -> " + str(p))
        # Sahkan tulis-balik: jangan percaya mesej fungsi, baca fail semula.
        try:
            teks = p.read_text(encoding="utf-8", errors="replace")
            c("  sahkan: penanda=%s (bait=%d)" % (PENANDA in teks, len(teks)))
        except OSError as e:
            c("  sahkan GAGAL baca: %r" % (e,))
        if hasil != "PATCH OK" and hasil != "sudah":
            # Diagnosis bila corak tidak padan: cetak tandatangan sebenar.
            try:
                teks = p.read_text(encoding="utf-8", errors="replace")
                i = teks.find("async def process_update")
                c("  tandatangan sebenar: " + repr(teks[i:i + 110]) if i >= 0 else
                  "  TIADA 'async def process_update' dalam fail")
            except OSError:
                pass
    c("=== selesai ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
