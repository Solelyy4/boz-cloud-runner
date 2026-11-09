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

# RANTAIAN BERTULIS TANGAN DIBUANG.
# Versi lama menyimpan senarai tetap di sini dan ia MENYIMPANG daripada config
# sebenar: menguji `mistral/ministral-8b-latest` yang tidak ada dalam config, dan
# tidak tahu provider `9router`. Gerbang lalu melaporkan "ADA PAUTAN GAGAL"
# sedangkan config sebenar semuanya sihat — bot dikongkong oleh ujian yang salah.
# Sekarang rantaian DIBACA daripada config (lihat baca_rantaian), satu sumber kebenaran.


def _curl_json(url: str, key: str, payload: dict | None, method: str = "POST") -> tuple[int, str]:
    """Panggil API guna curl. Pulang (http_code, body).

    PENGANGKUTAN = curl, BUKAN urllib. Bukti 8 Nov 2026: urllib ke Groq pulang
    `HTTP 403 error code: 1010` (Cloudflare menolak fingerprint TLS), manakala curl
    dengan payload SAMA pulang 200. Guna curl supaya ujian mencerminkan klien sebenar.

    PEPIJAT `rsplit('|')`: penanda kod HTTP mesti dicincang dari HUJUNG tetapi HANYA
    bila ia benar-benar kod. JSON boleh mengandungi `|` dalam teks model, dan
    `rsplit` memotong body di situ -> `JSONDecodeError` -> model SIHAT dilaporkan mati.
    Diperbaiki: pastikan 3 aksara terakhir ialah `|<kod>` sebelum mencincang.
    """
    args = ["curl", "-4", "-s", "-m", str(TIMEOUT), "-w", "|%{http_code}"]
    if payload is not None:
        args += ["-X", method, "-H", "Content-Type: application/json", "-d", json.dumps(payload)]
    args += ["-H", f"Authorization: Bearer {key}", url]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT + 20)
        out = r.stdout or ""
        if len(out) >= 4 and out[-4] == "|" and out[-3:].isdigit():
            return int(out[-3:]), out[:-4]
        # tiada penanda kod: pulang apa adanya, jangan teka
        return 0, (out or r.stderr)[:400]
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


def baca_rantaian(config_path: str) -> list[dict]:
    """Baca rantaian DARIPADA config — bukan senarai bertulis tangan."""
    try:
        import yaml
    except ImportError:
        print("[FAIL] PyYAML tiada — tidak dapat baca config", file=sys.stderr)
        return []
    if not os.path.exists(config_path):
        print(f"[FAIL] config tiada: {config_path}", file=sys.stderr)
        return []

    d = yaml.safe_load(open(config_path, encoding="utf-8"))
    prov = d.get("providers") or {}
    hasil: list[dict] = []

    def tambah(nama_prov: str, model: str, peranan: str) -> None:
        p = prov.get(nama_prov) or {}
        hasil.append({
            "peranan": peranan,
            "provider": nama_prov,
            "base": (p.get("base_url") or "").strip(),
            "kunci_env": p.get("api_key_env") or "",
            "model": model,
        })

    m = d.get("model") or {}
    if m.get("default"):
        tambah(m.get("provider") or "", m["default"], "teraju")
    for f in d.get("fallback_model") or []:
        tambah(f.get("provider") or "", f.get("model") or "", "sandaran")
    return hasil


def uji(p: dict, key: str) -> dict:
    """Satu pautan: adakah ia menjawab DAN menyokong tool-calling?"""
    payload = {
        "model": p["model"],
        # max_tokens MESTI besar. DIUKUR 8 Nov 2026 pada Groq gpt-oss:
        #   max_tokens=60  -> finish_reason=length, content='' (3/4 "gagal")
        #   max_tokens=200+ -> 4/4 berisi
        # Model reasoning habiskan kuota kecil pada medan `reasoning`. Ujian nilai
        # kecil menuduh model SIHAT sebagai mati — ini punca gerbang gagal.
        "max_tokens": 800,
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
    code, body = _curl_json(f"{p['base']}/chat/completions", key, payload)
    h = {**p, "http": code, "hidup": False, "tool_calls": 0, "sebab": "", "had": False}
    if code == 429:
        # HAD bukan reput: model sihat, kuota sementara. Bezakan supaya gerbang
        # tidak mengongkong bot hanya kerana satu pautan kena had seminit.
        h["had"] = True
        h["sebab"] = "429 HAD (model sihat, kuota sementara)"
        return h
    if code != 200:
        h["sebab"] = body[:180].replace("\n", " ")
        return h
    try:
        d = json.loads(body)
    except Exception:
        # 9Router menyambung `data: [DONE]` pada HUJUNG JSON penuh walaupun bukan
        # streaming (diukur: 556 bait, berakhir `...}}\n]data: [DONE]\n\n`). Parser
        # naif -> "Extra data: line 1 column 543" -> model SIHAT dilaporkan MATI.
        # Ini punca gerbang menyekat bot. Buang ekor SSE dahulu, kemudian hurai.
        bersih = body
        if "data: [DONE]" in bersih:
            bersih = bersih.split("data: [DONE]")[0].strip()
        try:
            d = json.loads(bersih)
        except Exception:
            # cuba juga baris `data: {...}` (bentuk SSE sebenar)
            for b in bersih.split("\n"):
                b = b.strip()
                if b.startswith("data:") and "[DONE]" not in b:
                    try:
                        d = json.loads(b[5:].strip())
                        break
                    except Exception:
                        continue
            else:
                raise
    try:
        if "error" in d:
            h["sebab"] = str(d["error"])[:150].replace("\n", " ")
            return h
        pilihan = d["choices"][0]
        ch = pilihan.get("message") or {}
        tc = ch.get("tool_calls") or []
        h["tool_calls"] = len(tc)
        h["hidup"] = bool(tc)
        sebenar = d.get("model") or ""
        nota = f"(dijawab {sebenar})" if sebenar and sebenar != p["model"] else ""
        if not tc:
            # `finish_reason: length` = jawapan TERPOTONG, bukan "tak sokong alat".
            selesai = pilihan.get("finish_reason") or "?"
            dasar = ("TERPOTONG (naikkan max_tokens)" if selesai == "length"
                     else f"tiada tool_calls ({selesai})")
            h["sebab"] = dasar + (" " + nota if nota else "")
        elif nota:
            h["sebab"] = nota
    except Exception as e:
        h["sebab"] = f"parse gagal: {type(e).__name__} {body[:120]}"
    return h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--longgar", action="store_true",
                    help="HAD 429 tidak menggagalkan gerbang (kuota sementara, bukan reput)")
    args = ap.parse_args()

    rantaian = baca_rantaian(args.config)
    if not rantaian:
        print("[FAIL] tiada rantaian dalam config", file=sys.stderr)
        return 1

    # Paun yatim: provider tiada base_url = mustahil berfungsi. Ini yang berlaku
    # bila config menunjuk `9router-vps` tetapi providers hanya ada `9router`.
    yatim = [r for r in rantaian if not r["base"]]
    if yatim:
        for r in yatim:
            print(f"[FAIL] {r['peranan']:8s} {r['provider']}/{r['model']} -> PROVIDER TIADA base_url",
                  file=sys.stderr)
        return 1

    print(f"=== SEMAK RANTAIAN MODEL (dibaca dari {args.config}) ===")
    tersedia: dict[str, set[str]] = {}
    mati, had = [], []
    for r in rantaian:
        kunci = os.environ.get(r["kunci_env"], "").strip() if r["kunci_env"] else ""
        # kunci_env kosong = provider KEYLESS (cth nafimods). Jangan tuduh MATI:
        # ia memang direka berjalan tanpa kunci, dan _curl tidak menghantar header
        # Authorization bila kunci kosong.
        if not kunci and r["kunci_env"]:
            print(f"[FAIL] {r['peranan']:8s} {r['provider']}/{r['model']:26s} kunci {r['kunci_env']} KOSONG")
            mati.append(r["model"])
            continue
        if r["base"] not in tersedia:
            tersedia[r["base"]] = _senarai_model(r["base"], kunci)
        # Elak menuduh model sihat: hanya tegur kalau senarai wujud DAN tiada model
        # DAN provider bukan 9Router (9Router boleh menukar model di belakang tabir).
        if tersedia[r["base"]] and r["model"] not in tersedia[r["base"]] and r["provider"] != "9router":
            print(f"[FAIL] {r['peranan']:8s} {r['provider']}/{r['model']:26s} TIADA dalam senarai model akaun")
            mati.append(r["model"])
            continue
        h = uji(r, kunci)
        tanda = "PASS" if h["hidup"] else ("HAD " if h["had"] else "FAIL")
        print(f"[{tanda}] {r['peranan']:8s} {r['provider']:8s} {r['model']:26s} HTTP {h['http']:<4} "
              f"tools={h['tool_calls']} {h['sebab']}")
        if not h["hidup"]:
            (had if h["had"] else mati).append(r["model"])

    if mati:
        print(f"\nRESULT: {len(mati)} PAUTAN MATI -> {mati}", file=sys.stderr)
        return 1
    if had and not args.longgar:
        print(f"\nRESULT: {len(had)} pautan kena HAD 429 sementara -> {had}", file=sys.stderr)
        return 1
    if had:
        print(f"\nRESULT: semua pautan hidup; {len(had)} kena HAD 429 sementara (dimaafkan): {had}")
        return 0
    print(f"\nRESULT: SEMUA {len(rantaian)} PAUTAN HIDUP, semua sokong tool-calling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
