#!/usr/bin/env python3
"""_boz_gerbang.py — penapis mesej KELUAR bot Telegram BOZ.

Dipasang ke dalam `adapter.py` oleh `pasang_gerbang.py` pada baris pertama
`async def send(...)`. Setiap mesej keluar melalui `tapis_keluar()`.

MASALAH YANG DIAWAL
===================
BOZ: "bila saya mesej je telegram bot, ia terus keluarkan link github, arahan,
dan ayat panjang-panjang walaupun saya tak suruh."

PUNCA: tiada apa-apa memeriksa mesej KELUAR. Prompt boleh dikurangkan, tetapi
model kecil tetap boleh memuntahkan tutorial. Gerbang ini menahannya.

REKA BENTUK (keselamatan bot diutamakan)
========================================
- Kalau modul penapis tiada / ralat -> pulang teks ASAL. Bot TIDAK PERNAH pecah
  kerana gerbang; ia hanya kehilangan penapis.
- Jenis mesej ditentukan daripada mesej MASUK terakhir BOZ. Kalau kita tidak tahu
  apa yang BOZ hantar, kita TIDAK memotong (fail-safe: jangan potong buta).
- Hanya chat BOZ (8043910371) ditapis. Pengguna lain tidak terjejas.
"""
from __future__ import annotations

import logging
import os
import sys
import threading

_LOG = logging.getLogger("boz_gerbang")
_L = threading.local()
STAT = {"diperiksa": 0, "dipotong": 0, "diluluskan": 0, "ralat": 0}

CHAT_BOZ = os.environ.get("BOZ_CHAT_ID", "8043910371").strip()
DILINDUNGI = os.environ.get("BOZ_GERBANG_OFF", "").strip() in ("1", "true", "yes")
_AKTIF = CHAT_BOZ if not DILINDUNGI else ""

# ---- import penapis dari repo runner -------------------------------------
_src_periksa = None
for _d in (os.environ.get("BOZ_RUNNER_DIR", ""),
           os.path.join(os.environ.get("GITHUB_WORKSPACE", ""), "boz-cloud-runner"),
           os.path.dirname(os.path.abspath(__file__)),
           os.getcwd()):
    if not _d:
        continue
    for _p in (os.path.join(_d, "scripts"), _d):
        if os.path.isfile(os.path.join(_p, "balas_pantas.py")):
            if _p not in sys.path:
                sys.path.insert(0, _p)
            try:
                from balas_pantas import periksa as _perc  # type: ignore
                _src_periksa = _perc
                break
            except Exception as e:  # pragma: no cover
                _LOG.warning("[gerbang] import balas_pantas gagal dari %s: %s", _p, e)
    if _src_periksa:
        break

if _src_periksa:
    _LOG.warning("[gerbang] AKTIF — penapis dimuat, chat BOZ=%s", _AKTIF or "(mati)")
else:
    _LOG.warning("[gerbang] penapis TIDAK dimuat — mesej dihantar tanpa tapisan")


def set_masuk(teks: str) -> None:
    """Rekod mesej BOZ yang terakhir supaya kita tahu jenis balasan yang sesuai."""
    try:
        _L.masuk = (teks or "")[:2000]
    except Exception:
        pass


def dapat_masuk() -> str:
    return getattr(_L, "masuk", "")


def tapis_keluar(chat_id, content) -> str:
    """Pintu utama. Pulang teks (mungkin dipotong). TIDAK PERNAH membuang mesej."""
    try:
        if not _AKTIF or str(chat_id).strip() != _AKTIF:
            return content
        if not content or not isinstance(content, str) or len(content) < 12:
            return content
        if _src_periksa is None:
            return content
        masuk = dapat_masuk()
        if not masuk:
            # Kita tidak tahu apa BOZ hantar -> jangan potong buta.
            STAT["diluluskan"] += 1
            return content
        STAT["diperiksa"] += 1
        r = _src_periksa(masuk, content)
        keluar = r.get("jawapan") or content
        if r.get("dipotong"):
            STAT["dipotong"] += 1
            _LOG.warning("[gerbang] dipotong jenis=%s sebab=%s %d->%d aksara",
                         r.get("jenis"), r.get("sebab"), r.get("aksara_asal"),
                         r.get("aksara_akhir"))
        else:
            STAT["diluluskan"] += 1
        return keluar if keluar.strip() else content
    except Exception as e:
        STAT["ralat"] += 1
        _LOG.warning("[gerbang] ralat (mesej asal dihantar): %s", e)
        return content
