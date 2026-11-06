#!/usr/bin/env python3
"""diagnosa_bot.py — sahkan setiap rantaian bot BERFUNGSI dari pelbagai sudut.

MENGAPA: BOZ minta bukti, bukan andaian. Skrip ini menguji setiap pautan dalam
rantaian bot dan mencetak VERDICT: OK / GAGAL untuk setiap satu. Ia dijalankan
di tempat bot berjalan supaya bukti itu sah untuk bot, bukan untuk laptop.

Guna:
  python scripts/diagnosa_bot.py            # uji semua
  python scripts/diagnosa_bot.py --ringkas  # hanya verdict
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import time
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    print("PERLU: python -m pip install httpx", file=sys.stderr)
    raise SystemExit(2)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
hasil: list[dict] = []


def catat(nama: str, ok: bool, bukti: str) -> None:
    hasil.append({"uji": nama, "ok": ok, "bukti": bukti})
    print(f"  [{'OK' if ok else 'GAGAL'}] {nama}: {bukti}")


def uji_dns(host: str) -> None:
    t0 = time.time()
    try:
        ips = sorted({ai[4][0] for ai in socket.getaddrinfo(host, 443, socket.AF_INET)})
        catat(f"DNS {host}", bool(ips), f"{ips[:3]} dalam {time.time()-t0:.2f}s")
    except Exception as e:
        catat(f"DNS {host}", False, f"{type(e).__name__}: {e}")


def uji_tcp(host: str, port: int = 443) -> None:
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=12):
            catat(f"TCP {host}:{port}", True, f"sambung dalam {time.time()-t0:.2f}s")
    except Exception as e:
        catat(f"TCP {host}:{port}", False, f"{type(e).__name__}: {e}")


def uji_https(url: str, had: int = 300) -> None:
    t0 = time.time()
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=25, follow_redirects=True)
        ok = r.status_code < 400
        catat(f"HTTPS {urlparse(url).netloc}", ok,
              f"HTTP {r.status_code} dalam {time.time()-t0:.2f}s ({len(r.text)} aksara)")
    except Exception as e:
        catat(f"HTTPS {urlparse(url).netloc}", False, f"{type(e).__name__}: {str(e)[:80]}")


def uji_telegram_api() -> None:
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not tok:
        catat("Telegram getMe", False, "TELEGRAM_BOT_TOKEN tiada dalam persekitaran")
        return
    try:
        r = httpx.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=25)
        d = r.json()
        catat("Telegram getMe", bool(d.get("ok")), f"bot={d.get('result',{}).get('username')} HTTP {r.status_code}")
    except Exception as e:
        catat("Telegram getMe", False, f"{type(e).__name__}: {str(e)[:80]}")


def uji_model() -> None:
    """Uji setiap model dalam rantai utama + fallback dengan kunci sebenar."""
    import yaml
    cfg_p = os.environ.get("HERMES_CONFIG") or os.path.join(os.environ.get("HERMES_HOME", "."), "config.yaml")
    try:
        cfg = yaml.safe_load(open(cfg_p, encoding="utf-8"))
    except Exception as e:
        catat("config.yaml", False, f"{type(e).__name__}: {e}")
        return
    catat("config.yaml", True, cfg_p)

    calon: list[tuple[str, str, str]] = []
    m = cfg.get("model") or {}
    if m.get("provider") and m.get("default"):
        calon.append((m["provider"], m["default"], "utama"))
    for f in (cfg.get("fallback_model") or []):
        if isinstance(f, dict) and f.get("provider"):
            calon.append((f["provider"], f.get("model", ""), "fallback"))

    prov = cfg.get("providers") or {}
    for provider, model, peranan in calon:
        pcfg = prov.get(provider) or {}
        env_name = pcfg.get("api_key_env") or ""
        key = os.environ.get(env_name, "") if env_name else ""
        base = (pcfg.get("base_url") or "").rstrip("/")
        if not base or not model:
            catat(f"model {provider}/{model} ({peranan})", False, "base_url/model tiada")
            continue
        if not key:
            catat(f"model {provider}/{model} ({peranan})", False,
                  f"{env_name or 'kunci'} KOSONG dalam persekitaran")
            continue
        try:
            r = httpx.post(f"{base}/chat/completions",
                           headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                           json={"model": model, "messages": [{"role": "user", "content": "balas: OK"}],
                                 "max_tokens": 10}, timeout=30)
            if r.status_code == 200:
                txt = r.json()["choices"][0]["message"]["content"][:30]
                catat(f"model {provider}/{model} ({peranan})", True, f"HTTP 200 -> {txt!r}")
            else:
                catat(f"model {provider}/{model} ({peranan})", False,
                      f"HTTP {r.status_code}: {r.text[:90]}")
        except Exception as e:
            catat(f"model {provider}/{model} ({peranan})", False, f"{type(e).__name__}: {str(e)[:70]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ringkas", action="store_true")
    args = ap.parse_args()

    print("=== DIAGNOSA RANTAIAN BOT ===")
    print("\n1) DNS")
    for h in ("api.telegram.org", "api.mistral.ai", "api.groq.com"):
        uji_dns(h)
    print("\n2) TCP")
    uji_tcp("api.telegram.org")
    uji_tcp("api.mistral.ai")
    print("\n3) HTTPS")
    uji_https("https://api.telegram.org")
    uji_https("https://api.mistral.ai/v1/models")
    print("\n4) Telegram API")
    uji_telegram_api()
    print("\n5) MODEL (rantaian utama + fallback)")
    uji_model()

    lulus = sum(1 for h in hasil if h["ok"])
    print(f"\n=== VERDICT: {lulus}/{len(hasil)} ujian lulus ===")
    for h in hasil:
        if not h["ok"]:
            print(f"  GAGAL: {h['uji']} — {h['bukti']}")
    out = os.environ.get("DIAGNOSA_OUT", "cari/diagnosa.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    json.dump(hasil, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"-> {out}")
    return 0 if lulus == len(hasil) else 1


if __name__ == "__main__":
    raise SystemExit(main())
