#!/usr/bin/env python3
"""Tulis nadi (heartbeat) supaya nod pengganti TAHU bot awan masih hidup.

PUNCA KONFLIK 409 YANG SEBENAR (dibuktikan 13 Nov 2026, bukan andaian):

  Repo `Solelyy4/boz-lab-node` menjalankan `telekey/standby.sh` — PENUNGGU
  yang memerhati nadi PC di gist:
      HB_URL = https://gist.githubusercontent.com/Solelyy4/d5cdf07.../raw/alive
      FRESH  = 180 saat

  Logiknya (komen dalam fail itu sendiri):
      PC hidup  (<180s)  -> nod senyap, PC yang poll Telegram
      PC senyap (>180s)  -> nod AMBIL ALIH poll Telegram

  Bukti nadi pada 13 Nov 2026 16:56 UTC:
      nadi mentah  = 1794468509
      sekarang     = 1794588990
      umur nadi    = 120,481 saat = 33.5 JAM   (had ialah 180 saat)

  Jadi nod percaya "PC mati sejak 33 jam" lalu merampas token Telegram.
  Bot awan (boz-cloud-runner) poll TOKEN YANG SAMA -> kedua-dua 409.
  `ensure_cloud.sh` (cron setiap 15 minit) melihat gateway mati lalu memulakan
  semula -> 409 lagi -> GELUNG ABADI. Bot bisu selama-lamanya.

  SIAPA YANG SEPATUTNYA MENULIS NADI? Tiada sesiapa. Grep seluruh laptop dan
  repo mendapati hanya `standby.sh` MEMBACA nadi; tiada penulis wujud. Reka
  bentuk itu tidak pernah dilengkapkan.

  Pembaikan: skrip ini menulis nadi semasa gateway awan hidup, jadi nod melihat
  PC "hidup" dan kekal senyap — seperti yang direka.

SENSI MASA: ditulis setiap 60s (had nod ialah 180s, jadi ada 3x margin).

Guna:
    python tulis_nadi.py            # tulis sekali (untuk ujian)
    python tulis_nadi.py --loop 60  # tulis berulang (mod gateway)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Gist yang diperhatikan oleh standby.sh. Sama seperti HB_URL dalam fail itu.
GIST_ID = "d5cdf07feb91d5d89337476d2f9db7ae"
FAIL_NADI = "alive"
API = "https://api.github.com/gists/%s" % GIST_ID


def token_github():
    """Cari token GitHub. BOZ_PAT dahulu (gist ini milik BOZ), kemudian GITHUB_TOKEN."""
    for nama in ("BOZ_PAT", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT"):
        nilai = os.environ.get(nama, "").strip()
        if nilai:
            return nilai
    return ""


def tulis_nadi(tok):
    """Kemas kini gist dengan masa epoch semasa. Pulang True bila berjaya."""
    if not tok:
        print("NADI GAGAL: tiada token GitHub (BOZ_PAT / GITHUB_TOKEN)")
        return False
    masa = str(int(time.time()))
    muatan = json.dumps({
        "files": {
            FAIL_NADI: {"content": masa}
        }
    }).encode("utf-8")
    req = urllib.request.Request(API, data=muatan, method="PATCH")
    req.add_header("Authorization", "Bearer %s" % tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "boz-nadi/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            kod = resp.status
            body = json.loads(resp.read().decode("utf-8", "replace"))
        # Sahkan nilai benar-benar tersimpan (bukan sekadar HTTP 200).
        disimpan = ""
        files = body.get("files") or {}
        if FAIL_NADI in files:
            disimpan = (files[FAIL_NADI].get("content") or "").strip()
        if disimpan == masa:
            print("NADI OK: %s (masa epoch ditulis dan disahkan)" % masa)
            return True
        print("NADI AMARAN: HTTP %s tetapi kandungan tidak sepadan (disimpan=%r)" % (kod, disimpan))
        return False
    except urllib.error.HTTPError as e:
        print("NADI GAGAL: HTTP %s %s" % (e.code, e.reason))
        return False
    except Exception as e:
        print("NADI GAGAL: %s" % e)
        return False


def main():
    p = argparse.ArgumentParser(description="Tulis nadi BOZ supaya nod pengganti kekal senyap.")
    p.add_argument("--loop", type=int, default=0,
                   help="Selang saat antara tulisan (0 = tulis sekali sahaja). Cadangan 60.")
    p.add_argument("--maks", type=int, default=0,
                   help="Berhenti selepas N tulisan (0 = tiada had). Untuk ujian.")
    a = p.parse_args()

    tok = token_github()
    if not tok:
        print("NADI GAGAL: tiada token. Set BOZ_PAT atau GITHUB_TOKEN.")
        return 1

    if a.loop <= 0:
        return 0 if tulis_nadi(tok) else 1

    n = 0
    while True:
        ok = tulis_nadi(tok)
        n += 1
        if a.maks and n >= a.maks:
            return 0 if ok else 1
        # Jeda walaupun gagal: cuba semula setiap selang. Nodi mungkin tidak
        # terjangkau sementara (rangkaian), tetapi nadi basi = nod rampas token.
        time.sleep(a.loop)


if __name__ == "__main__":
    sys.exit(main())
