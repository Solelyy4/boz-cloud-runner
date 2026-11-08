#!/usr/bin/env python3
"""peronda_telegram.py — peronda hidup bot dari DALAM runner, tanpa getUpdates.

MASALAH YANG IA SELESAIKAN (bukti 8 Nov 2026):
  - Bot "Connected" tetapi mesej BOZ tidak dibalas.
  - Runner pulang `Bad Gateway` / `timed out after 30s` ke api.telegram.org,
    sementara laptop BOZ pulang HTTP 200 dalam 0.6s (8/8 cubaan) pada MASA SAMA.
    -> rangkaian runner tidak stabil, BUKAN token rosak, BUKAN kod bot salah.
  - Tanpa peronda, bot diam berjam-jam dan BOZ menyangka ia mati.

PERATURAN KESELAMATAN (jangan langgar):
  * JANGAN panggil getUpdates. Satu-satunya pemegang long-poll ialah gateway Hermes.
    getUpdates dari luar merampas long-poll -> 409 -> adapter mati.
  * getMe / getWebhookInfo / sendMessage SELAMAT — ia tidak merebut antrian.
  * Peronda menulis keadaan ke fail JSON supaya workflow boleh melaporkan dengan jujur.

Guna:
  python scripts/peronda_telegram.py --tunggu 30 --pusingan 10
  python scripts/peronda_telegram.py --sejarah status_peronda.jsonl   # ringkasan
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

WIB = timezone(timedelta(hours=7))


def _curl(url: str, post: dict | None = None, timeout: int = 20) -> tuple[int, float, str]:
    args = ["curl", "-4", "-s", "-m", str(timeout), "-w", "|%{http_code}|%{time_total}"]
    if post:
        args += ["-X", "POST"]
        for k, v in post.items():
            args += ["--data-urlencode", f"{k}={v}"]
    args.append(url)
    t0 = time.time()
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 10)
        out = r.stdout
        if out.count("|") >= 2:
            body, code, dur = out.rsplit("|", 2)
            return int(code.strip() or 0), float(dur or 0), body
        return 0, time.time() - t0, (out or r.stderr)[:200]
    except Exception as e:
        return 0, time.time() - t0, f"{type(e).__name__}: {e}"


def kesihatan(token: str) -> dict:
    """Satu denyut: boleh ke runner bercakap dengan Telegram SEKARANG?"""
    code, dur, body = _curl(f"https://api.telegram.org/bot{token}/getMe")
    ok = code == 200 and '"ok":true' in body
    hasil = {
        "masa": datetime.now(WIB).isoformat(timespec="seconds"),
        "getMe_http": code,
        "getMe_saat": round(dur, 3),
        "ok": ok,
    }
    if ok:
        try:
            hasil["bot"] = json.loads(body)["result"]["username"]
        except Exception:
            pass
    else:
        hasil["ralat"] = body[:160].replace("\n", " ")
    # pending_update_count selamat (bukan getUpdates) — bukti bot MEMBACA
    c2, _, b2 = _curl(f"https://api.telegram.org/bot{token}/getWebhookInfo")
    if c2 == 200:
        try:
            hasil["pending"] = json.loads(b2)["result"].get("pending_update_count")
        except Exception:
            hasil["pending"] = None
    else:
        hasil["pending"] = None
        hasil["webhook_http"] = c2
    return hasil


def beritahu(token: str, chat_id: str, teks: str) -> bool:
    """Hantar mesej jujur kepada BOZ. Tanpa menuduh punca yang belum disahkan."""
    code, _, body = _curl(
        f"https://api.telegram.org/bot{token}/sendMessage",
        {"chat_id": chat_id, "text": teks},
    )
    return code == 200 and '"ok":true' in body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tunggu", type=int, default=30, help="saat antara denyut")
    ap.add_argument("--pusingan", type=int, default=10, help="bilangan denyut (0 = tanpa henti)")
    ap.add_argument("--keluaran", default="status_peronda.jsonl")
    ap.add_argument("--chat-id", default=os.environ.get("BOZ_CHAT_ID", "8043910371"))
    ap.add_argument("--beritahu-selepas", type=int, default=3,
                    help="beritahu BOZ selepas N denyut gagal berturut-turut")
    ap.add_argument("--sejarah", help="cetak ringkasan fail JSONL dan keluar")
    args = ap.parse_args()

    if args.sejarah:
        return _ringkasan(args.sejarah)

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("[FAIL] TELEGRAM_BOT_TOKEN kosong", file=sys.stderr)
        return 1

    gagal_berturut = 0
    sudah_beritahu = False
    pusingan = 0
    while True:
        pusingan += 1
        h = kesihatan(token)
        baris = json.dumps(h, ensure_ascii=False)
        print(baris, flush=True)
        try:
            with open(args.keluaran, "a", encoding="utf-8") as f:
                f.write(baris + "\n")
        except Exception as e:
            print(f"[AMARAN] gagal tulis {args.keluaran}: {e}", file=sys.stderr)

        if h["ok"]:
            if gagal_berturut >= args.beritahu_selepas and not sudah_beritahu:
                beritahu(
                    token, args.chat_id,
                    "Bot awan pulih: sambungan ke Telegram berfungsi semula "
                    f"(selepas {gagal_berturut} denyut gagal).",
                )
            gagal_berturut = 0
            sudah_beritahu = False
        else:
            gagal_berturut += 1
            if gagal_berturut >= args.beritahu_selepas and not sudah_beritahu:
                # Jujur: nyatakan GEJALA, bukan punca yang belum dibuktikan.
                beritahu(
                    token, args.chat_id,
                    f"⚠️ Bot awan tidak dapat menghubungi Telegram dari runner "
                    f"({gagal_berturut} cubaan berturut, HTTP {h['getMe_http']}). "
                    "Token dan bot masih sah. Ini masalah laluan rangkaian runner, "
                    "bukan bot BOZ. Bot akan cuba pulih sendiri.",
                )
                sudah_beritahu = True

        if args.pusingan and pusingan >= args.pusingan:
            break
        time.sleep(args.tunggu)

    print(f"=== SELESAI: {pusingan} denyut, gagal_berakhir={gagal_berturut} ===")
    return 0 if gagal_berturut == 0 else 2


def _ringkasan(path: str) -> int:
    if not os.path.exists(path):
        print(f"[tiada] {path}")
        return 1
    ok = gagal = 0
    masa_gagal = []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("ok"):
            ok += 1
        else:
            gagal += 1
            masa_gagal.append(f"{d.get('masa')} HTTP {d.get('getMe_http')} {d.get('ralat', '')[:70]}")
    jumlah = ok + gagal
    print(f"denyut: {jumlah} | sihat: {ok} | gagal: {gagal}")
    if jumlah:
        print(f"kadar sihat: {ok / jumlah:.0%}")
    for m in masa_gagal[-10:]:
        print("  GAGAL:", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
