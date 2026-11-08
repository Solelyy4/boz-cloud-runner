#!/usr/bin/env python3
"""sah_model.py — sahkan SETIAP pautan rantaian model HIDUP sebelum gateway mula.

SEBAB: bot pernah mati dengan `rebuilt_restart_limit_exceeded` kerana:
  - fallback #1 `mistral-medium-latest` pulang 429 rate_limited
  - fallback #3 `open-mistral-nemo` sudah TIADA dalam akaun
  - aux vision `pixtral-12b-latest` sudah TIADA dalam akaun
Bot nampak HIDUP tetapi mustahil menjawab. Skrip ini menjadikan kegagalan itu
KETARA (exit 1) sebelum bot menerima satu mesej pun.

Guna: python scripts/sah_model.py [--tulis-config PATH]
Keluar 0 = semua pautan hidup. Keluar 1 = ada pautan mati (dengan sebab).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

TIMEOUT = 45
CURL = "curl"

# Rantaian muktamad. Disahkan hidup 8 Nov 2026 (tool_calls=1 pada setiap satu).
RANTAIAN = [
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "ministral-14b-latest"),
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "ministral-8b-latest"),
    ("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b"),
    ("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "qwen/qwen3.8-27b"),
]


def _curl_json(url: str, key: str, payload: dict | None, method: str = "POST") -> tuple[int, str]:
    """Panggil API guna curl. Pulang (http_code, body).

    PENGANGKUTAN = curl, BUKAN urllib. Bukti 8 Nov 2026: urllib ke Groq pulang
    `HTTP 403 error code: 1010` (Cloudflare menolak fingerprint TLS), manakala curl
    dengan payload SAMA pulang 200. Guna curl supaya ujian mencerminkan klien sebenar.
    """
    args = [CURL, "-4", "-s", "-m", str(TIMEOUT), "-w", "|%{http_code}"]
    if payload is not None:
        args += ["-X", method, "-H", "Content-Type: application/json", "-d", json.dumps(payload)]
    args += ["-H", f"Authorization: Bearer {key}", url]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT + 15)
        out = r.stdout
        if "|" not in out:
            return 0, (out or r.stderr)[:300]
        body, code = out.rsplit("|", 1)
        return int(code.strip() or 0), body
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _senarai_model(url: str, key: str) -> set[str]:
    """Senarai model yang BENAR-BENAR wujud dalam akaun (elak fallback reput)."""
    code, body = _curl_json(f"{url}/models", key, None, "GET")
    if code != 200:
        return set()
    try:
        return {m.get("id") for m in json.loads(body).get("data", [])}
    except Exception:
        return set()


def uji(p: str, url: str, key: str, model: str) -> dict:
    """Satu pautan: adakah ia menjawab DAN menyokong tool-calling?"""
    payload = {
        "model": model,
        "max_tokens": 120,
        "messages": [{"role": "user", "content": "Cari 'malaysia'. Guna alat."}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Cari internet",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
        }],
    }
    code, body = _curl_json(f"{url}/chat/completions", key, payload)
    hasil = {"provider": p, "model": model, "http": code, "hidup": False, "tool_calls": 0, "sebab": ""}
    if code != 200:
        hasil["sebab"] = body[:180].replace("\n", " ")
        return hasil
    try:
        d = json.loads(body)
        ch = (d.get("choices") or [{}])[0].get("message", {})
        tc = ch.get("tool_calls") or []
        hasil["tool_calls"] = len(tc)
        hasil["hidup"] = True
        if not tc:
            hasil["sebab"] = "jawab tetapi TIADA tool_calls (bot tak boleh guna alat)"
        elif isinstance(ch.get("content"), list):
            hasil["sebab"] = "pulang blok thinking (boleh jadi jawapan pelik)"
    except Exception as e:
        hasil["sebab"] = f"parse gagal: {type(e).__name__} {body[:120]}"
    return hasil


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tulis-config", help="tulis config.yaml rantaian ini ke PATH (python, bukan sed)")
    args = ap.parse_args()

    env = dict(os.environ)
    hilang = [k for _, _, k, _ in RANTAIAN if not env.get(k)]
    if hilang:
        print(f"[FAIL] env kunci KOSONG: {sorted(set(hilang))}", file=sys.stderr)
        return 1

    # 1. Semak kewujudan model dalam akaun (429/tiada = mati, tanpa perlu panggil chat)
    tersedia: dict[str, set[str]] = {}
    for url in {u for _, u, _, _ in RANTAIAN}:
        kunci = next(k for _, u, k, _ in RANTAIAN if u == url)
        tersedia[url] = _senarai_model(url, env[kunci])

    mati = []
    print("=== SEMAK RANTAIAN MODEL ===")
    for p, url, kenv, model in RANTAIAN:
        if tersedia[url] and model not in tersedia[url]:
            print(f"[FAIL] {p}/{model:24s} TIADA dalam akaun (senarai model tidak mengandunginya)")
            mati.append(model)
            continue
        h = uji(p, url, env[kenv], model)
        tanda = "PASS" if h["hidup"] else "FAIL"
        print(f"[{tanda}] {p}/{model:24s} HTTP {h['http']:<4} tools={h['tool_calls']} {h['sebab']}")
        if not h["hidup"]:
            mati.append(model)

    if args.tulis_config:
        tulis_config(args.tulis_config)

    if mati:
        print(f"\nRESULT: {len(mati)} PAUTAN MATI -> {mati}", file=sys.stderr)
        return 1
    print(f"\nRESULT: SEMUA {len(RANTAIAN)} PAUTAN HIDUP")
    return 0


def tulis_config(path: str) -> None:
    """Tulis blok rantaian dengan python. Sahkan saiz SELEPAS tulis.

    PERATURAN (dari kegagalan sebenar): jangan sekali-kali tulis config daripada
    sed/pemboleh ubah satu baris — pernah menjadikan config 4,458 bait jadi 45 bait
    dan bot hilang providers/skills/platforms.
    """
    blok = """# Blok rantaian model dijana oleh scripts/sah_model.py.
# Setiap pautan disahkan HIDUP sebelum gateway mula. Jangan tambah model
# tanpa mengesahkannya dahulu — fallback reput = bot hidup tetapi mustahil menjawab.
model:
  provider: mistral
  default: ministral-14b-latest
  api_mode: chat_completions
  context_window: 262144
  max_tokens: 8192

providers:
  mistral:
    base_url: https://api.mistral.ai/v1
    api_key_env: MISTRAL_API_KEY
  groq:
    base_url: https://api.groq.com/openai/v1
    api_key_env: GROQ_API_KEY

fallback_model:
  - provider: mistral
    model: ministral-8b-latest
  - provider: groq
    model: openai/gpt-oss-120b
  - provider: groq
    model: qwen/qwen3.8-27b
"""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(blok)
    saiz = os.path.getsize(path)
    if saiz < 300:
        raise SystemExit(f"[FAIL] config terlalu kecil ({saiz} bait) — tulis gagal")
    print(f"config rantaian ditulis: {path} ({saiz} bait)")


if __name__ == "__main__":
    sys.exit(main())
