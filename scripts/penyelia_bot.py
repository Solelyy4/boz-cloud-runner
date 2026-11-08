#!/usr/bin/env python3
"""penyelia_bot.py — ejen penyelia autonomi untuk bot Telegram BOZ.

BOZ minta "bina sendiri agent dalam ni untuk meramaikan lagi uruskan telegram bot".
Ejen ini mengulang kitaran tetap dan MEMBAIKI masalah yang dapat dikesan sendiri,
kemudian melapor HANYA bila ada perubahan keadaan (bukan spam setiap kitaran).

Apa ia periksa setiap kitaran
-----------------------------
1. Run gateway terkini: adakah `in_progress`? Berapa lama?
2. `gw_trace.log`: adakah gerbang menyambung ke Telegram? Adakah trace bergerak?
3. `JAGA RANTAIAN`: berapa pautan HIDUP? Teraju hidup atau sandaran?
4. Adakah runner melaporkan kunci tidak sah pada provider yang kuncinya ADA?
5. Jurang jadual: adakah run tamat sebelum cron berikutnya (mesej tidak dibaca)?

Tindakan autonomi
-----------------
- Run tamat / tiada run hidup      -> cetus `telegram.yml`
- Run tergantung > timeout          -> batalkan, cetus semula
- Teraju MATI, sandaran hidup       -> lapor (jangan tukar config sendiri; gerbang
                                        sudah memilih sandaran, menukar boleh
                                        merosakkan rantaian yang diuji)
- Kunci dilaporkan tidak sah        -> lapor + jalankan uji-tokenomix.yml untuk
                                        mengesahkan dari runner (bukan tekaan)
- Mesej BOZ tidak dijawab           -> lapor dengan masa & lori trace

Penggunaan
----------
    python scripts/penyelia_bot.py --sekali      # satu kitaran (cron)
    python scripts/penyelia_bot.py --kitaran 300 # berulang setiap 5 minit
    python scripts/penyelia_bot.py --senyap      # jangan hantar Telegram

Kredential dibaca dari env atau $HERMES_HOME/secrets; TIADA kunci ditulis ke log.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

REPO = "Solelyy4/boz-cloud-runner"
WIB = timezone(timedelta(hours=7))
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".penyelia_state.json")


def _home() -> str:
    h = os.environ.get("HERMES_HOME")
    if h:
        return h
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes")
    return os.path.expanduser("~/AppData/Local/hermes")


def _gh() -> str:
    """Cari gh.exe — jangan andaikan PATH."""
    for c in (os.path.join(_home(), "bin", "gh.exe"),
              os.path.join(_home(), "bin", "gh"),
              "gh"):
        if os.path.sep in c:
            if os.path.exists(c):
                return c
        else:
            return c
    return "gh"


def gh_api(jalur: str, kaedah: str = "GET") -> tuple[bool, str]:
    cmd = [_gh(), "api", f"repos/{REPO}/{jalur}"]
    if kaedah != "GET":
        cmd += ["-X", kaedah]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        return r.returncode == 0, r.stdout
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def baca_trace() -> str:
    ok, out = gh_api("contents/gw_trace.log")
    if not ok:
        return ""
    try:
        return base64.b64decode(json.loads(out)["content"]).decode("utf-8", "replace")
    except Exception:
        return ""


def run_terkini() -> dict:
    ok, out = gh_api("actions/workflows/telegram.yml/runs?per_page=3")
    if not ok:
        return {}
    try:
        rs = json.loads(out)["workflow_runs"]
    except Exception:
        return {}
    return rs[0] if rs else {}


def keadaan_run(r: dict) -> dict:
    """Kira umur run dan sama ada ia wajar dibatalkan."""
    if not r:
        return {"ada": False}
    mula = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
    umur = (datetime.now(timezone.utc) - mula).total_seconds() / 60
    return {
        "ada": True,
        "id": r["id"],
        "status": r["status"],
        "conclusion": r.get("conclusion"),
        "umur_min": round(umur, 1),
        "hidup": r["status"] in ("in_progress", "queued"),
    }


def hurai_rantaian(trace: str) -> dict:
    """Ambil blok JAGA RANTAIAN terakhir -> {hidup: n, mati: n, teraju: bool, butir: []}."""
    blok = trace.split("JAGA RANTAIAN")[-1] if "JAGA RANTAIAN" in trace else ""
    hidup = re.findall(r"\[HIDUP\]\s+(\S+)\s+(\S+)", blok)
    mati = re.findall(r"\[MATI\s*\]\s+(\S+)\s+(\S+)\s+(.{0,60})", blok)
    return {
        "hidup": len(hidup),
        "mati": len(mati),
        "senarai_hidup": hidup,
        "senarai_mati": [(p, m) for p, m, _ in mati],
        "sentinel": "TERAJU MATI" if "TERAJU MATI" in blok else (
            "SEMUA MATI" if "SEMUA MATI" in blok else "OK"),
        "kunci_salah": "invalid_api_key" in blok or "Invalid API key" in blok,
    }


def sambung_telegram(trace: str) -> dict:
    """Adakah gerbang benar-benar menyambung (bukan sekadar proses hidup)?"""
    return {
        "polling": "Connected to Telegram" in trace or "polling mode" in trace,
        "sambung_semula": len(re.findall(r"SAMBUNG OK", trace)),
        "ralat_rangkaian": len(re.findall(r"ConnectError|NetworkError|Timed out", trace)),
    }


def hantar(teks: str, senyap: bool = False) -> None:
    if senyap:
        print(f"[SENYAP] {teks}")
        return
    p = os.path.join(_home(), "secrets", "telegram_bot_token.real")
    if not os.path.exists(p):
        print(f"[TIADA TOKEN] {teks}")
        return
    tok = open(p, encoding="utf-8").read().strip()
    data = json.dumps({"chat_id": "8043910371", "text": teks[:4000],
                       "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/sendMessage", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            print(f"[HANTAR] HTTP {r.status}")
    except Exception as e:
        print(f"[GAGAL HANTAR] {type(e).__name__}: {e}")


def cetus_workflow(nama: str) -> bool:
    cmd = [_gh(), "workflow", "run", nama, "--repo", REPO, "--ref", "master"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if r.returncode == 0:
            print(f"[CETUS] {nama} dihantar")
            return True
        print(f"[CETUS GAGAL] {nama}: {r.stderr.strip()[:150]}")
    except Exception as e:
        print(f"[CETUS RALAT] {nama}: {type(e).__name__}")
    return False


def batal_run(rid: str) -> bool:
    try:
        r = subprocess.run([_gh(), "run", "cancel", str(rid), "--repo", REPO],
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def muat_state() -> dict:
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def simpan_state(s: dict) -> None:
    try:
        json.dump(s, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception:
        pass


def kitaran(senyap: bool = False, auto_cetus: bool = True) -> int:
    """Satu pusingan pemeriksaan + tindakan. Pulang kod keluar."""
    now = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    trace = baca_trace()
    r = run_terkini()
    k = keadaan_run(r)
    rant = hurai_rantaian(trace)
    tg = sambung_telegram(trace)

    masalah: list[str] = []
    tindakan: list[str] = []

    # --- 1. Adakah bot benar-benar hidup? ---
    if not k.get("ada"):
        masalah.append("Tiada run gateway dijumpai")
        if auto_cetus and cetus_workflow("telegram.yml"):
            tindakan.append("cetus telegram.yml")
    elif not k["hidup"]:
        masalah.append(f"Run {k['id']} sudah tamat ({k['conclusion']}) — bot MATI")
        if auto_cetus and cetus_workflow("telegram.yml"):
            tindakan.append("cetus telegram.yml")
    elif k["umur_min"] > 400:
        # timeout-minutes 400: melebihi ini bermakna run tergantung
        masalah.append(f"Run {k['id']} tergantung {k['umur_min']}m > had 400m")
        if auto_cetus and batal_run(k["id"]):
            tindakan.append(f"batal run {k['id']}")
            time.sleep(15)
            if cetus_workflow("telegram.yml"):
                tindakan.append("cetus semula")

    # --- 2. Sambungan Telegram ---
    if k.get("hidup") and not tg["polling"]:
        masalah.append("Gerbang hidup tetapi tiada 'Connected to Telegram' dalam trace")
    if tg["ralat_rangkaian"] > 0:
        masalah.append(f"{tg['ralat_rangkaian']} ralat rangkaian dalam trace")

    # --- 3. Kesihatan rantaian model ---
    if rant["sentinel"] == "SEMUA MATI":
        masalah.append("SEMUA model MATI — bot tidak boleh menjawab")
    elif rant["sentinel"] == "TERAJU MATI":
        masalah.append(f"Teraju MATI, {rant['hidup']} sandaran hidup — "
                       f"kualiti menurun, jawapan mungkin menolak tugasan")
    if rant["kunci_salah"]:
        masalah.append("Provider melaporkan 'Invalid API key' walaupun kunci didaftar")

    # --- 4. Lapor HANYA bila keadaan berubah ---
    sidik = "|".join(sorted(masalah))
    st = muat_state()
    berubah = sidik != st.get("sidik_akhir")

    baris = [
        f"<b>PENYELIA BOT</b> — {now}",
        "",
        f"Run: <code>{k.get('id', '-')}</code> {k.get('status', '-')} "
        f"({k.get('umur_min', 0)}m)",
        f"Telegram: {'polling OK' if tg['polling'] else 'TIADA SAMBUNGAN'} "
        f"| sambung semula: {tg['sambung_semula']}",
        f"Model hidup: {rant['hidup']} | mati: {rant['mati']} | {rant['sentinel']}",
    ]
    if rant["senarai_hidup"]:
        baris.append("Hidup: " + ", ".join(f"{p}/{m}" for p, m in rant["senarai_hidup"]))
    if masalah:
        baris += ["", "<b>Masalah:</b>"] + [f"• {m}" for m in masalah]
    if tindakan:
        baris += ["", "<b>Tindakan:</b>"] + [f"• {t}" for t in tindakan]
    if not masalah:
        baris += ["", "Semua sihat."]

    teks = "\n".join(baris)
    print(teks.replace("<b>", "").replace("</b>", "")
          .replace("<code>", "").replace("</code>", ""))

    if berubah or tindakan:
        hantar(teks, senyap)
        st["sidik_akhir"] = sidik
        st["masa"] = now
        simpan_state(st)
    else:
        print("[TIADA PERUBAHAN — tidak hantar]")

    return 0 if not masalah else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Ejen penyelia bot Telegram BOZ")
    ap.add_argument("--sekali", action="store_true", help="satu kitaran sahaja")
    ap.add_argument("--kitaran", type=int, default=0,
                    help="ulang setiap N saat (0 = sekali)")
    ap.add_argument("--senyap", action="store_true", help="jangan hantar Telegram")
    ap.add_argument("--tanpa-cetus", action="store_true",
                    help="jangan cetus/batal workflow sendiri")
    a = ap.parse_args()

    if a.kitaran <= 0:
        return kitaran(a.senyap, not a.tanpa_cetus)

    print(f"[PENYELIA] berulang setiap {a.kitaran}s — Ctrl+C untuk berhenti")
    while True:
        try:
            kitaran(a.senyap, not a.tanpa_cetus)
        except KeyboardInterrupt:
            print("\n[PENYELIA] berhenti")
            return 0
        except Exception as e:
            print(f"[PENYELIA] ralat kitaran: {type(e).__name__}: {e}")
        time.sleep(a.kitaran)


if __name__ == "__main__":
    sys.exit(main())
