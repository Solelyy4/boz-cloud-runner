#!/usr/bin/env python3
"""
BOZ SELF-TEST — uji bot seperti pengguna sebenar, tanpa BOZ perlu taip.

Kenapa: BOZ mahu sistem yang MENYELESAIKAN SENDIRI, bukan menyuruh dia uji.
Skrip ini:
  1. Hantar mesej ujian ke bot melalui TELEGRAM_BOT_TOKEN (sendMessage ke chat BOZ)
     -- mustahil: bot tidak boleh hantar KE dirinya dan harap ia proses.
  Penyelesaian sebenar: uji ENJIN bot secara headless (hermes agent), bukan
  penghantaran mesej. Ini kerana:
    - Menghantar mesej melalui Bot API tidak mencetuskan pemprosesan gateway.
    - getUpdates dari luar akan merebut long-poll -> 409 (dilarang keras).
  Jadi kita uji bahagian yang boleh gagal: sama ada ejen boleh guna alat
  (fetch.py, web_search, web_extract) dan pulangkan hasil sebenar.

Guna:
    python scripts/selftest_agent.py                # ujian penuh
    python scripts/selftest_agent.py --ujian fetch  # satu ujian
Hasil: state/selftest.json + stdout ringkasan.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

WIB = timezone(timedelta(hours=7))
STATE = Path("state")
STATE.mkdir(exist_ok=True)


def now() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")


def cari_python_hermes() -> str | None:
    """Cari venv Hermes yang ada hermes_cli + ddgs + telegram."""
    kandidat = []
    home = os.environ.get("HERMES_HOME", "")
    if home:
        kandidat += [str(p) for p in Path(home).glob("installs/*/environments/*/venv/bin/python")]
    kandidat += [str(p) for p in Path("home/installs").glob("*/environments/*/venv/bin/python")]
    terbalk = None
    for p in kandidat:
        if not Path(p).exists():
            continue
        try:
            r = subprocess.run([p, "-c",
                                "import hermes_cli, ddgs, telegram"],
                               capture_output=True, timeout=30)
            if r.returncode == 0:
                return p
            if terbalk is None and subprocess.run(
                    [p, "-c", "import hermes_cli"], capture_output=True).returncode == 0:
                terbalk = p
        except Exception:
            continue
    return terbalk


def ujian_fetch() -> dict:
    """Ujian 1: fetch.py jalan dan pulangkan hasil sebenar."""
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "scripts/fetch.py", "python asyncio", "--kira", "4"],
                           capture_output=True, text=True, timeout=90)
        out = r.stdout.strip()
        ok = "SIAP:" in out and r.returncode == 0
        return {"nama": "fetch.py", "lulus": ok,
                "masa_s": round(time.time() - t0, 1),
                "bukti": out.splitlines()[:3], "rc": r.returncode,
                "err": r.stderr.strip()[:200] if not ok else ""}
    except Exception as e:
        return {"nama": "fetch.py", "lulus": False, "masa_s": round(time.time() - t0, 1),
                "bukti": [], "rc": -1, "err": f"{type(e).__name__}: {e}"}


def ujian_fetch_extract() -> dict:
    """Ujian 2: fetch.py --extract benar-benar ambil kandungan halaman."""
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "scripts/fetch.py", "python asyncio",
                            "--kira", "3", "--extract", "2"],
                           capture_output=True, text=True, timeout=150)
        out = r.stdout.strip()
        ok = "kandungan:" in out and "0/" not in out
        return {"nama": "fetch.py --extract", "lulus": ok,
                "masa_s": round(time.time() - t0, 1),
                "bukti": [l for l in out.splitlines() if "kandungan" in l or "ambil" in l][:3],
                "rc": r.returncode, "err": r.stderr.strip()[:200] if not ok else ""}
    except Exception as e:
        return {"nama": "fetch.py --extract", "lulus": False,
                "masa_s": round(time.time() - t0, 1), "bukti": [], "rc": -1,
                "err": f"{type(e).__name__}: {e}"}


def ujian_alat_hermes() -> dict:
    """Ujian 3: alat Hermes (web_search/web_extract) jalan dalam venv Hermes."""
    py = cari_python_hermes()
    if not py:
        return {"nama": "alat_hermes", "lulus": False, "masa_s": 0,
                "bukti": [], "rc": -1, "err": "venv Hermes tidak dijumpai"}
    skrip = r'''
import asyncio, json, sys
hasil = {}
try:
    from tools.web_tools import web_search_tool
    r = web_search_tool("python asyncio", limit=3)
    web = (r.get("data") or {}).get("web") or []
    hasil["web_search"] = len(web)
except Exception as e:
    hasil["web_search"] = "GAGAL: %s: %s" % (type(e).__name__, str(e)[:150])
try:
    from tools.web_tools import web_extract_tool
    r = web_extract_tool(["https://example.com"])
    res = r.get("results") or []
    isi = (res[0].get("content") or "") if res else ""
    hasil["web_extract"] = len(isi)
except Exception as e:
    hasil["web_extract"] = "GAGAL: %s: %s" % (type(e).__name__, str(e)[:150])
print("HASIL:" + json.dumps(hasil))
'''
    t0 = time.time()
    try:
        r = subprocess.run([py, "-c", skrip], capture_output=True, text=True, timeout=180,
                           env={**os.environ, "HERMES_HOME": os.environ.get("HERMES_HOME", "home")})
        baris = [l for l in r.stdout.splitlines() if l.startswith("HASIL:")]
        hasil = json.loads(baris[0][6:]) if baris else {}
        ws, we = hasil.get("web_search"), hasil.get("web_extract")
        ok = isinstance(ws, int) and ws > 0
        return {"nama": "alat_hermes", "lulus": ok, "masa_s": round(time.time() - t0, 1),
                "bukti": [f"web_search={ws}", f"web_extract={we}"], "rc": r.returncode,
                "err": "" if ok else str(hasil)[:250]}
    except Exception as e:
        return {"nama": "alat_hermes", "lulus": False, "masa_s": round(time.time() - t0, 1),
                "bukti": [], "rc": -1, "err": f"{type(e).__name__}: {e}"}


UJIAN = {
    "fetch": ujian_fetch,
    "extract": ujian_fetch_extract,
    "hermes": ujian_alat_hermes,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ujian", choices=list(UJIAN), default="")
    args = ap.parse_args()

    pilih = [args.ujian] if args.ujian else list(UJIAN)
    hasil = {"masa": now(), "ujian": []}
    for nama in pilih:
        print(f"[{now()}] uji {nama} ...", flush=True)
        h = UJIAN[nama]()
        hasil["ujian"].append(h)
        tanda = "LULUS" if h["lulus"] else "GAGAL"
        print(f"  {tanda} {h['nama']} ({h['masa_s']}s) {h['bukti']}", flush=True)
        if not h["lulus"]:
            print(f"      err: {h['err']}", flush=True)

    lulus = sum(1 for h in hasil["ujian"] if h["lulus"])
    jumlah = len(hasil["ujian"])
    hasil["ringkasan"] = f"{lulus}/{jumlah} lulus"
    (STATE / "selftest.json").write_text(json.dumps(hasil, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    print(f"RINGKASAN: {hasil['ringkasan']} -> state/selftest.json")
    return 0 if lulus == jumlah else 1


if __name__ == "__main__":
    sys.exit(main())
