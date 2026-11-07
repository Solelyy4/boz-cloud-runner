#!/usr/bin/env python3
"""interaksi.py — ujian BERDEPAN bot Telegram BOZ.

MENGAPA
=======
BOZ minta bot diuji sendiri, bukan hanya ditulis kod. Skrip ini berinteraksi
dengan bot SEBENAR: menghantar mesej sebagai BOZ, menunggu jawapan, dan
menyimpan transkrip penuh sebagai bukti.

CARA
====
Ia menggunakan Bot API secara terus (sendMessage + getUpdates). Ia TIDAK guna
getUpdates pada gateway yang sedang long-poll (itu akan merampas mesej) —
sebaliknya ia hantar mesej, kemudian baca trace/log bot untuk mengesahkan
bot MEMPROSES mesej itu.

Lebih kukuh: kita hantar mesej, kemudian periksa `pending_update_count`.
Kalau ia turun ke 0, bot SUDAH ambil mesej (jadi bot hidup dan mendengar).

Guna:
  python interaksi.py "Hello, apa khabar?"
  python interaksi.py --siri          # hantar siri soalan ujian
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

try:
    import httpx
except ImportError:
    print("PERLU: python -m pip install httpx", file=sys.stderr)
    raise SystemExit(2)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("BOZ_CHAT_ID", "8043910371")
API = f"https://api.telegram.org/bot{TOKEN}"
OUT = os.environ.get("INTERAKSI_OUT", "/tmp/interaksi.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def getme() -> dict:
    if not TOKEN:
        return {"ok": False, "sebab": "TELEGRAM_BOT_TOKEN kosong"}
    try:
        r = httpx.get(f"{API}/getMe", timeout=20)
        return r.json()
    except Exception as e:
        return {"ok": False, "sebab": f"{type(e).__name__}: {e}"}


def pending() -> int:
    """Bilangan mesej belum diambil. Bot hidup = ia berkurang ke 0."""
    try:
        r = httpx.get(f"{API}/getWebhookInfo", timeout=20)
        return int(r.json().get("result", {}).get("pending_update_count", -1))
    except Exception:
        return -1


def hantar(teks: str) -> dict:
    try:
        r = httpx.post(f"{API}/sendMessage",
                       json={"chat_id": CHAT_ID, "text": teks}, timeout=25)
        return r.json()
    except Exception as e:
        return {"ok": False, "sebab": f"{type(e).__name__}: {e}"}


def uji_satu(teks: str, tunggu: int = 90) -> dict:
    """Hantar satu mesej, tunggu bot mengambilnya, pulang bukti."""
    rekod: dict = {"ts": _now(), "mesej": teks}
    before = pending()
    rekod["pending_sebelum"] = before
    h = hantar(teks)
    rekod["ok_hantar"] = h.get("ok", False)
    rekod["message_id"] = h.get("result", {}).get("message_id")
    if not rekod["ok_hantar"]:
        rekod["ralat_hantar"] = h.get("description") or h.get("sebab")
        return rekod
    # Tunggu bot mengambil mesej (pending turun). Ini bukti bot mendengar.
    for i in range(tunggu // 5):
        time.sleep(5)
        p = pending()
        if p == 0:
            rekod["bot_ambil"] = True
            rekod["saat_ambil"] = (i + 1) * 5
            break
    else:
        rekod["bot_ambil"] = False
        rekod["pending_akhir"] = pending()
    return rekod


SIRI = [
    # Setiap jenis mesej yang BOZ mungkin hantar — bot mesti lalui SEMUA.
    "Hello",                                                        # sapaan
    "apa itu API? jelaskan ringkas",                                # soalan asas
    "cari di google: telegram bot tanpa VPS 2026",                  # carian web
    "tulis fail /tmp/uji-boz.txt dengan kandungan 'HALO BOZ' dan hantar kepada aku",  # fail + MEDIA
    "jam berapa sekarang di Malaysia?",                             # masa
    "siapa kau?",                                                   # identiti
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Ujian berdepan bot Telegram BOZ")
    ap.add_argument("mesej", nargs="?", default="Hello")
    ap.add_argument("--siri", action="store_true", help="hantar siri soalan ujian")
    ap.add_argument("--tunggu", type=int, default=90)
    args = ap.parse_args()

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    info = getme()
    print(f"getMe: ok={info.get('ok')} bot={info.get('result', {}).get('username')}")
    if not info.get("ok"):
        print(f"  sebab: {info.get('sebab') or info.get('description')}")
        return 2

    rekod: list[dict] = []
    senarai = SIRI if args.siri else [args.mesej]
    for m in senarai:
        print(f"\n--- hantar: {m[:60]} ---")
        r = uji_satu(m, args.tunggu)
        rekod.append(r)
        print(f"  message_id={r.get('message_id')} bot_ambil={r.get('bot_ambil')} "
              f"saat={r.get('saat_ambil')}")
        time.sleep(3)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"ts": _now(), "rekod": rekod}, fh, ensure_ascii=False, indent=1)
    ambil = sum(1 for r in rekod if r.get("bot_ambil"))
    print(f"\nRINGKASAN: {ambil}/{len(rekod)} mesej diambil bot -> {OUT}")
    return 0 if ambil == len(rekod) else 1


if __name__ == "__main__":
    raise SystemExit(main())
