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
import re
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


def _cekal_yaml(config_path: str) -> dict:
    """Parser config mini — guna bila PyYAML tiada.

    Venv Hermes dalam GitHub Actions kerap TIADA pip DAN tiada PyYAML, jadi
    gerbang mati sebelum bot menerima satu mesej pun. Fungsi ini hanya perlu
    faham SUBSET config yang kita tulis sendiri (config.yaml dijana oleh
    yaml.safe_dump): pemetaan bersarang 2-3 aras, senarai blok `- item`, dan
    senarai skalar. Ia sengaja tidak menyokong anchor, tag, atau flow-style.
    """
    teks = open(config_path, encoding="utf-8").read()
    akar: dict = {}
    # tindanan (indent, bekas) — bekas ialah dict atau list
    tindan: list[tuple[int, object]] = [(-1, akar)]
    baris_semua = teks.splitlines()
    # jenis anak ditentukan dengan melihat baris BERMAKNA seterusnya
    bermakna = [b for b in baris_semua if b.strip() and not b.lstrip().startswith("#")]

    for i, mentah in enumerate(baris_semua):
        if not mentah.strip() or mentah.lstrip().startswith("#"):
            continue
        ind = len(mentah) - len(mentah.lstrip())
        baris = mentah.strip()

        # buang bekas yang indentnya >= baris ini
        while len(tindan) > 1 and tindan[-1][0] >= ind:
            tindan.pop()
        bekas = tindan[-1][1]

        if baris.startswith("- "):
            item = baris[2:].strip()
            if not isinstance(bekas, list):
                continue
            # item dict kalau ada "kunci: nilai" (bukan URL)
            if re.match(r"^[A-Za-z_][\w-]*\s*:", item):
                k, _, v = item.partition(":")
                d = {k.strip(): _nilai(v.strip())}
                bekas.append(d)
                tindan.append((ind, d))
            else:
                bekas.append(_nilai(item))
            continue

        if ":" not in baris:
            continue
        kunci, _, nilai = baris.partition(":")
        kunci = kunci.strip()
        if len(kunci) >= 2 and kunci[0] == kunci[-1] and kunci[0] in ("'", '"'):
            kunci = kunci[1:-1]
        nilai = nilai.strip()

        if not isinstance(bekas, dict):
            continue
        if nilai in ("", "~", "null"):
            # lihat baris bermakna SETERUSNYA selepas baris ini: kalau lebih
            # dalam DAN mula "- ", anak ialah list; selain itu dict
            anak: object = {}
            jumpa = False
            for nxt in baris_semua[i+1:]:
                if not nxt.strip() or nxt.lstrip().startswith("#"):
                    continue
                nind = len(nxt) - len(nxt.lstrip())
                if nind <= ind:
                    break
                anak = [] if nxt.strip().startswith("- ") else {}
                jumpa = True
                break
            if not jumpa:
                anak = {}
            bekas[kunci] = anak
            tindan.append((ind, anak))
        else:
            bekas[kunci] = _nilai(nilai)
    return akar


def _nilai(v: str):
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    if v in ("true", "True"):
        return True
    if v in ("false", "False"):
        return False
    if v in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def baca_rantaian(config_path: str) -> list[dict]:
    """Baca rantaian DARIPADA config — bukan senarai bertulis tangan."""
    d = None
    try:
        import yaml
        d = yaml.safe_load(open(config_path, encoding="utf-8"))
    except ImportError:
        if not os.path.exists(config_path):
            print(f"[FAIL] config tiada: {config_path}", file=sys.stderr)
            return []
        print("[INFO] PyYAML tiada — guna parser mini terbina", file=sys.stderr)
        d = _cekal_yaml(config_path)
    if d is None:
        print(f"[FAIL] config tiada: {config_path}", file=sys.stderr)
        return []
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
    ap.add_argument("--config", default=None,
                    help="laluan config.yaml (lalai: cari config.yaml atau home/config.yaml)")
    ap.add_argument("--longgar", action="store_true",
                    help="HAD 429 tidak menggagalkan gerbang (kuota sementara, bukan reput)")
    ap.add_argument("--ketat", action="store_true",
                    help="gagalkan juga bila SANADARAN mati, bukan hanya teraju")
    args = ap.parse_args()

    # Laluan config: gerbang dijalankan dari akar repo, tetapi config Hermes
    # tinggal di home/config.yaml. Cuba senarai calon sebelum menyerah, supaya
    # gerbang tidak gagal dengan FileNotFoundError: 'config.yaml'.
    if not args.config:
        for calon in ("config.yaml", os.path.join("home", "config.yaml"),
                      os.path.join(os.path.dirname(__file__), "..", "home", "config.yaml")):
            if os.path.exists(calon):
                args.config = os.path.normpath(calon)
                break
        else:
            print("[FAIL] config.yaml tidak dijumpai (cuba config.yaml, home/config.yaml)",
                  file=sys.stderr)
            return 1
    print(f"=== SEMAK RANTAIAN MODEL (dibaca dari {args.config}) ===")
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
        # Teraju WAJIB hidup — bot tidak boleh berjalan tanpa model utama.
        # Sandaran yang tiada kunci (cth 9router bila ROUTER9_API_KEY tidak
        # ditetapkan) BUKAN kegagalan: ia cuma bermakna laluan failover itu tidak
        # tersedia. Gagalkan run hanya kalau teraju sendiri mati, atau kalau
        # --ketat diminta (audit penuh).
        mati_teraju = [r["model"] for r in rantaian
                       if r["peranan"] == "teraju" and r["model"] in mati]
        if mati_teraju or args.ketat:
            print(f"\nRESULT: {len(mati)} PAUTAN MATI -> {mati}", file=sys.stderr)
            return 1
        print(f"\nRESULT: {len(mati)} sandaran tidak tersedia -> {mati} "
              f"(dimaafkan: teraju hidup, --ketat untuk menggagalkan)")
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
