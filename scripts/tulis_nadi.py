#!/usr/bin/env python3
"""Tulis nadi (heartbeat) supaya nod pengganti kekal senyap — rintang had API.

KENAPA DITULIS SEMULA (13 Nov 2026, bukti sebenar):

  Versi pertama menulis terus ke gist melalui GitHub REST API. Berfungsi
  sebentar, kemudian MATI dengan:
      NADI GAGAL: HTTP 403 Forbidden     (x4 dalam gw_trace.log)

  Punca sebenar (bukan tekaan):
      gh api /rate_limit -> "API rate limit exceeded for user ID 330849825"

  BOZ_PAT ialah Personal Access Token. Setiap panggilan REST API kepadanya
  dikira dalam had 5000/jam YANG SAMA dengan semua kegunaan lain: workflow,
  ensure_cloud.sh (cron 15 minit), penjejak trace (setiap 90s), peronda, dan
  nadi ini. Ia habis dengan cepat.

  Bila nadi gagal -> nadi basi -> nod boz-lab-node (telekey/standby.sh)
  percaya PC sudah mati -> merampas TELEGRAM_BOT_TOKEN -> bot awan dapat 409
  -> adapter PARKED -> BOT BISU.

  Bukti yang dikutip serentak:
      umur nadi            = 291 saat   (had nod: 180s)
      NADI GAGAL 403       = 4 kali
      pending (peronda)    = 0          (bot tidak pernah terima update)
      long-poll SEBELUM    = BEBAS      (tiada pemegang)
      long-poll SELEPAS    = BEBAS      (bot memang tidak polling)

PENDEKATAN BAHARU — TIADA REST API LANGSUNG:
  Nadi ditulis ke fail dalam repo kerja, kemudian dipush melalui protokol GIT
  (bukan REST). Git push tidak berkongsi had 5000/jam itu, dan runner sudah
  punya kelayakan git (clone dibuat dengan BOZ_PAT).
  Nod membaca fail melalui raw.githubusercontent.com yang disajikan CDN — juga
  tiada had API.

Guna:
    python tulis_nadi.py --repo /path/ke/repo            # sekali
    python tulis_nadi.py --repo /path/ke/repo --loop 45  # berterusan
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Fail nadi dalam repo kerja. Nod membacanya melalui raw.githubusercontent.com:
#   https://raw.githubusercontent.com/Solelyy4/boz-cloud-runner/master/NADI
FAIL_NADI = "NADI"

# Fallback gist (untuk kes nod masih menunjuk ke sana). Dipakai hanya bila
# git push gagal, supaya sekurang-kurangnya satu saluran tetap hidup.
GIST_ID = "d5cdf07feb91d5d89337476d2f9db7ae"


def _token():
    for nama in ("BOZ_PAT", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT"):
        v = os.environ.get(nama, "").strip()
        if v:
            return v
    return ""


def _gist_fallback(masa):
    """Cuba gist sebagai saluran kedua. Tidak maut (gist boleh kena had API)."""
    tok = _token()
    if not tok:
        return False
    muatan = json.dumps({"files": {"alive": {"content": masa}}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/gists/%s" % GIST_ID, data=muatan, method="PATCH")
    req.add_header("Authorization", "Bearer %s" % tok)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "boz-nadi/2.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
        if (body.get("files", {}).get("alive", {}).get("content") or "").strip() == masa:
            print("NADI gist: OK (saluran kedua)")
            return True
        print("NADI gist: kandungan tidak sepadan")
        return False
    except urllib.error.HTTPError as e:
        print("NADI gist gagal: HTTP %s (bukan maut)" % e.code)
        return False
    except Exception as e:
        print("NADI gist gagal: %s (bukan maut)" % e)
        return False


def tulis_nadi(repo):
    """Tulis masa epoch ke fail nadi dan push melalui git. True bila berjaya."""
    laluan = os.path.join(repo, FAIL_NADI)
    masa = str(int(time.time()))
    try:
        with open(laluan, "w", encoding="utf-8", newline="\n") as f:
            f.write(masa + "\n")
    except Exception as e:
        print("NADI GAGAL: tidak dapat tulis %s: %s" % (laluan, e))
        return _gist_fallback(masa)

    # Sahkan fail di disk sebenar (read-after-write).
    try:
        with open(laluan, encoding="utf-8") as f:
            balik = f.read().strip()
    except Exception as e:
        print("NADI GAGAL: tidak dapat baca semula: %s" % e)
        return _gist_fallback(masa)
    if balik != masa:
        print("NADI GAGAL: kandungan tidak sepadan (tulis=%s baca=%s)" % (masa, balik))
        return _gist_fallback(masa)

    subprocess.run(["git", "-C", repo, "add", "-f", FAIL_NADI], capture_output=True)
    subprocess.run(
        ["git", "-C", repo, "-c", "user.email=bot@local", "-c", "user.name=bot",
         "commit", "-q", "-m", "nadi %s" % masa],
        capture_output=True)

    for _ in range(3):
        r = subprocess.run(["git", "-C", repo, "push", "origin", "HEAD:master"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print("NADI OK: %s (git push, tanpa REST API)" % masa)
            return True
        # Hujung jauh mungkin bergerak (penjejak trace push setiap 90s).
        subprocess.run(["git", "-C", repo, "fetch", "origin", "master", "-q"],
                       capture_output=True)
        subprocess.run(["git", "-C", repo, "rebase", "-q", "origin/master"],
                       capture_output=True)
        time.sleep(3)

    print("NADI GAGAL: git push tidak berjaya selepas 3 cubaan")
    return _gist_fallback(masa)


def main():
    p = argparse.ArgumentParser(
        description="Tulis nadi BOZ melalui git push (rintang had REST API).")
    p.add_argument("--repo", default=os.getcwd(), help="Direktori repo kerja")
    p.add_argument("--loop", type=int, default=0,
                   help="Selang saat antara tulisan (0 = sekali). Cadangan 45.")
    p.add_argument("--maks", type=int, default=0,
                   help="Berhenti selepas N tulisan (0 = tiada had).")
    a = p.parse_args()

    if not os.path.isdir(os.path.join(a.repo, ".git")):
        print("NADI GAGAL: %s bukan repo git" % a.repo)
        return 1

    if a.loop <= 0:
        return 0 if tulis_nadi(a.repo) else 1

    n = 0
    while True:
        ok = tulis_nadi(a.repo)
        n += 1
        if a.maks and n >= a.maks:
            return 0 if ok else 1
        # Jeda walaupun gagal: nadi basi = nod merampas token. Cuba lagi.
        time.sleep(a.loop)


if __name__ == "__main__":
    sys.exit(main())
