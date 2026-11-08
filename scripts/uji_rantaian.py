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
    profil = {
        "sembang": {"messages": [{"role": "user", "content": "Balas satu perkataan: OK"}], "max_tokens": 60},
        "alat": {
            "messages": [{"role": "user", "content": "Senaraikan fail dalam folder sekarang. Guna alat terminal."}],
            "max_tokens": 300,
            "tools": ALAT,
        },
    }

    lulus_penuh = True
    for nama, p in profil.items():
        print(f"\n=== PROFIL: {nama.upper()} ===")
        for prov, model in rantaian:
            payload = {"model": model, **p}
            code, body = curl_json(f"{prov_cfg[prov]['base_url']}/chat/completions", kunci(prov), payload)
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
                        isi = ch.get("content")
                        ok = bool(isi) and not isinstance(isi, list)
                        nota = repr(str(isi)[:44]) if ok else f"content={type(isi).__name__}"
                else:
                    nota = str(d.get("error", d))[:100]
            except Exception:
                nota = body[:100].replace("\n", " ")
            if not ok:
                lulus_penuh = False
            print(f"  [{'PASS' if ok else 'FAIL'}] {prov:8s} {model:24s} HTTP {code:<4} {nota}")

    print(f"\nRESULT: {'SEMUA PAUTAN LULUS' if lulus_penuh else 'ADA PAUTAN GAGAL'}")
    return 0 if lulus_penuh else 1


if __name__ == "__main__":
    sys.exit(main())
