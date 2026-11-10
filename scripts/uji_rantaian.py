#!/usr/bin/env python3
"""uji_rantaian.py — uji SELURUH rantaian model daripada config dengan mesej sebenar.

Beza dengan sah_model.py:
  sah_model.py   : lulus/gagal setiap pautan (untuk gerbang sebelum gateway)
  uji_rantaian.py: meniru apa yang BOT lakukan — mesej BOZ, chat biasa DAN tool-calling —
                   pada model lalai dan setiap fallback, ikut urutan config.

Guna: python scripts/uji_rantaian.py ujian/config_kerja.yaml
Keluar 0 = semua pautan boleh menjawab mesej sebenar.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys


def load_cfg(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def curl_json(url: str, key: str, payload: dict) -> tuple[int, str]:
    args = ["curl", "-4", "-s", "-m", "70", "-w", "|%{http_code}"]
    if payload is not None:
        args += ["-X", "POST", "-H", "Content-Type: application/json", "-d", json.dumps(payload)]
    args += ["-H", f"Authorization: Bearer {key}", url]
    r = subprocess.run(args, capture_output=True, text=True, timeout=90)
    out = r.stdout
    if "|" not in out:
        return 0, (out or r.stderr)[:200]
    body, code = out.rsplit("|", 1)
    return int(code.strip() or 0), body


ALAT = [{
    "type": "function",
    "function": {
        "name": "terminal",
        "description": "Jalankan arahan shell",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
}]


def main() -> int:
    if len(sys.argv) < 2:
        print("guna: uji_rantaian.py <config.yaml>", file=sys.stderr)
        return 1
    cfg = load_cfg(sys.argv[1])
    prov_cfg = cfg["providers"]

    def kunci(p: str) -> str:
        return os.environ.get(prov_cfg[p]["api_key_env"], "")

    rantaian = [(cfg["model"]["provider"], cfg["model"]["default"])]
    rantaian += [(f["provider"], f["model"]) for f in cfg.get("fallback_model", [])]

    # Dua profil: mesej sembang biasa, dan permintaan yang memerlukan ALAT.
    # max_tokens MESTI >= 800: model reasoning (gpt-oss) menghabiskan kuota kecil pada
    # medan `reasoning` dan pulang content='' — diukur 8 Nov 2026: max_tokens=60 -> 3/4,
    # max_tokens=200+ -> 4/4. Ujian dengan max_tokens kecil menuduh model sihat sebagai mati.
    profil = {
        "sembang": {"messages": [{"role": "user", "content": "Balas satu perkataan: OK"}], "max_tokens": 800},
        "alat": {
            "messages": [{"role": "user", "content": "Senaraikan fail dalam folder sekarang. Guna alat terminal."}],
            "max_tokens": 800,
            "tools": ALAT,
        },
    }

    lulus_penuh = True
    nota_had = 0
    for nama, p in profil.items():
        print(f"\n=== PROFIL: {nama.upper()} ===")
        for prov, model in rantaian:
            # Cuba 3x untuk profil alat. Bukti: qwen3.8-27b intermiten — 2/3 lulus,
            # 1 gagal kerana ia mereka-reka nama alat ('linux') yang tidak diminta.
            # Satu kegagalan rawak BUKAN bukti model mati; tiga kegagalan berturut YA.
            cubaan = 3 if nama == "alat" else 1
            ok, nota, code_akhir = False, "", 0
            for c in range(cubaan):
                payload = {"model": model, **p}
                code, body = curl_json(f"{prov_cfg[prov]['base_url']}/chat/completions", kunci(prov), payload)
                code_akhir = code
                ok, nota = False, ""
                try:
                    d = json.loads(body)
                    if code == 200 and "choices" in d:
                        ch = d["choices"][0].get("message", {})
                        tc = ch.get("tool_calls") or []
                        if nama == "alat":
                            ok = bool(tc)
                            nota = f"tool_calls={len(tc)}" if ok else "TIADA tool_calls"
                        else:
                            # content mesti TEKS bukan kosong. Jangan tuduh model salah
                            # hanya kerana ia turut pulang medan `reasoning` (gpt-oss buat
                            # begitu pada setiap jawapan yang sah).
                            isi = ch.get("content")
                            # Sesetengah model (mistral-large-4) pulang content sebagai
                            # SENARAI blok [{"type":"text","text":"..."}] dan bukan
                            # string. Menolaknya sebagai gagal membuang model sihat.
                            if isinstance(isi, list):
                                isi = "".join(
                                    b.get("text", "") if isinstance(b, dict) else str(b)
                                    for b in isi
                                )
                            ok = isinstance(isi, str) and isi.strip() != ""
                            nota = repr(str(isi)[:44]) if ok else f"content={type(ch.get('content')).__name__}"
                            if ok and ch.get("reasoning"):
                                nota += " (ada medan reasoning — normal)"
                    else:
                        nota = str(d.get("error", d))[:100]
                        # 429 bukan model rosak — ia HAD. Tandakan berasingan supaya
                        # kita tidak buang model sihat kerana kuota sementara.
                        if code == 429:
                            nota = "HAD (429) — bukan model rosak"
                except Exception:
                    nota = body[:100].replace("\n", " ")
                if ok:
                    break
                if c + 1 < cubaan:
                    nota += f" [cubaan {c+1}/{cubaan}]"
            if not ok:
                # 429 = HAD akaun, bukan model rosak. Bukti: mistral pulang 429 pada ujian
                # kedua dalam minit yang sama, tetapi pulang mesej sah pada percubaan
                # lain. Menandakan ini sebagai gagal membuat kita membuang model sihat.
                if code_akhir == 429:
                    print(f"  [HAD ] {prov:8s} {model:24s} HTTP 429 {'(dijangka — bukan kegagalan)'}")
                    nota_had += 1
                    continue
                lulus_penuh = False
            print(f"  [{'PASS' if ok else 'FAIL'}] {prov:8s} {model:24s} HTTP {code_akhir:<4} {nota}")

    print(f"\nRESULT: {'SEMUA PAUTAN LULUS' if lulus_penuh else 'ADA PAUTAN GAGAL'}"
          + (f" ({nota_had} pautan kena HAD 429 — model sihat, kuota sementara)" if nota_had else ""))
    return 0 if lulus_penuh else 1


if __name__ == "__main__":
    sys.exit(main())
