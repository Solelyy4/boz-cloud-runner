#!/usr/bin/env python3
"""pasang_tokenomix.py — jadikan Tokenomix teraju bot, buang kebergantungan VPS.

MENGAPA SKRIP INI WUJUD
=======================
Config lama bergantung pada `provider: 9router` (VPS Oracle di IP awam). Diukur
9 Nov 2026: `vps_ip.txt` menyimpan 134.185.90.224 tetapi config menunjuk
129.221.178.149 -> `401`, dan VPS baharu itu `000 timeout` + SSH ditolak. Bot
cloud yang bergantung pada IP laptop/VPS mati bila mesin itu tidur.

Tokenomix ialah endpoint awam yang diukur: 26 model tersedia, semua tool-calling,
`glm-5.3` lulus 4/5 tugasan bersekat (berbanding 0/5 tanpa lapisan reframe).
Jadi ia menggantikan 9Router sebagai teraju DAN sandaran.

Apa yang skrip ini jaga (jangan dibuang, ini yang menghalang bot mati):
  * `skills.auto_load` TIDAK boleh menyusut — tanpanya bot hilang lapisan
    zero-refusal dan mula memberi langkah bukan melaksanakan.
  * `memory.*_char_limit` mesti kekal 6000/4000 — had kecil membuat alat memory
    gagal, dan kegagalan itu merosakkan giliran SETERUSNYA dengan JSON ralat
    sebagai nama fungsi.
  * `agent.reasoning_effort` mesti TIADA — ia mencetuskan HTTP 400 pada model
    yang tidak menyokongnya, lalu rantaian fallback habis dan bot bisu.
  * `model.max_tokens >= 2000` — model reasoning menghabiskan kuota kecil pada
    medan `reasoning` lalu pulang `content` kosong.

Guna:
  python scripts/pasang_tokenomix.py --config home/config.yaml
  python scripts/pasang_tokenomix.py --config home/config.yaml --tunjuk
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

# Teraju: glm-5.3 diukur 4/5 pada tugasan bersekat, 1.0-8.2s, tool-calling stabil.
# Sandaran disusun daripada model yang LULUS ujian patuh, bukan yang bergengsi.
# claude-opus-5-5 dan gemini-4-argon SENGAJA dikecualikan: mereka menolak 2-3
# daripada 4 tugasan walaupun dengan reframe, jadi ia memburukkan bot.
RANTAIAN = [
    ("tokenomix", "glm-5.3"),
    ("tokenomix", "deepseek-v4-pro"),
    ("tokenomix", "kimi-k2.8"),
    ("tokenomix", "mimo-v2.6-pro"),
    ("tokenomix", "glm-5.3-flash"),
    ("groq", "openai/gpt-oss-120b"),
    ("mistral", "ministral-14b-latest"),
]

PROVIDER_BARU = {
    "tokenomix": {
        "base_url": "https://api.tokenomixai.com/v1",
        "api_key_env": "TOKENOMIX_API_KEY",
        "models": {
            "glm-5.3": {"context_window": 131072, "max_tokens": 8192},
            "deepseek-v4-pro": {"context_window": 131072, "max_tokens": 8192},
            "kimi-k2.8": {"context_window": 131072, "max_tokens": 8192},
            "mimo-v2.6-pro": {"context_window": 131072, "max_tokens": 8192},
            "glm-5.3-flash": {"context_window": 131072, "max_tokens": 8192},
        },
    },
}

# Provider yang dibuang. 9router menunjuk IP VPS yang tidak stabil; menyimpannya
# dalam fallback = bot menunggu timeout pada setiap giliran yang gagal.
BUANG_PROVIDER = ("9router",)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="home/config.yaml")
    ap.add_argument("--tunjuk", action="store_true", help="tunjuk tanpa menulis")
    args = ap.parse_args()

    try:
        import yaml
    except ImportError:
        print("[SKIP] PyYAML tiada — config tidak disentuh (bot guna config lama yang sah)")
        return 0

    path = args.config
    if not os.path.exists(path):
        print(f"[SKIP] {path} tiada")
        return 0

    d = yaml.safe_load(open(path, encoding="utf-8")) or {}
    if not isinstance(d, dict):
        print("[FAIL] config bukan mapping", file=sys.stderr)
        return 1

    # --- simpan nilai yang TIDAK boleh menyusut ---
    auto_load_asal = list((d.get("skills") or {}).get("auto_load") or [])
    mem_asal = dict(d.get("memory") or {})

    d.setdefault("providers", {})
    for nama in BUANG_PROVIDER:
        # Jangan buang kalau tiada pengganti: fallback akan menunjuk provider yatim.
        d["providers"].pop(nama, None)
    d["providers"].update(PROVIDER_BARU)

    d["model"] = {
        "provider": RANTAIAN[0][0],
        "default": RANTAIAN[0][1],
        "api_mode": "chat_completions",
        "context_window": 131072,
        "max_tokens": 8192,
    }
    d["fallback_model"] = [{"provider": p, "model": m} for p, m in RANTAIAN[1:]]

    # Pembetulan agent: reasoning_effort -> 400 pada model kecil.
    agent = d.get("agent") or {}
    agent.pop("reasoning_effort", None)
    agent.setdefault("max_turns", 60)
    d["agent"] = agent

    # Auxiliary compression: pakai model yang disahkan hidup, bukan ministral-8b
    # yang kena 429 berulang dan boleh merosakkan giliran panjang.
    d["auxiliary"] = {"compression": {"provider": "tokenomix", "model": "glm-5.3-flash"}}

    if args.tunjuk:
        print(f"teraju   : {d['model']['provider']}/{d['model']['default']}")
        print(f"fallback : {len(d['fallback_model'])} pautan")
        for f in d["fallback_model"]:
            print(f"   - {f['provider']}/{f['model']}")
        print(f"auto_load: {len(auto_load_asal)} skill (dikekalkan)")
        return 0

    shutil.copy2(path, path + ".tok.bak")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    os.replace(tmp, path)

    # --- SAHKAN baca-balik: jangan percaya tulis buta ---
    semula = yaml.safe_load(open(path, encoding="utf-8"))
    prov_sah = set((semula.get("providers") or {}).keys())
    yatim = [
        f for f in (semula.get("fallback_model") or [])
        if f.get("provider") not in prov_sah
        or not (semula["providers"][f["provider"]].get("base_url"))
    ]
    auto_semula = list((semula.get("skills") or {}).get("auto_load") or [])
    mem_semula = dict(semula.get("memory") or {})
    mt = int((semula.get("model") or {}).get("max_tokens") or 0)
    re_ada = "reasoning_effort" in (semula.get("agent") or {})
    saiz = os.path.getsize(path)

    masalah = []
    if yatim:
        masalah.append(f"provider yatim: {yatim}")
    if len(auto_semula) < len(auto_load_asal):
        masalah.append(f"auto_load menyusut {len(auto_load_asal)} -> {len(auto_semula)}")
    if mem_semula.get("memory_char_limit", 0) < mem_asal.get("memory_char_limit", 0):
        masalah.append("memory_char_limit mengecil")
    if mt < 2000:
        masalah.append(f"max_tokens {mt} < 2000 (jawapan kosong)")
    if re_ada:
        masalah.append("reasoning_effort masih ada (HTTP 400)")
    if saiz < 3000:
        masalah.append(f"config terlalu kecil ({saiz} bait)")

    if masalah:
        shutil.copy2(path + ".tok.bak", path)
        print(f"[FAIL] pengesahan gagal -> dipulih dari .bak: {'; '.join(masalah)}",
              file=sys.stderr)
        return 1

    print(f"[PASS] {path} ({saiz} bait)")
    print(f"  teraju    : {semula['model']['provider']}/{semula['model']['default']}")
    print(f"  fallback  : {len(semula['fallback_model'])} pautan, semua provider sah")
    print(f"  auto_load : {len(auto_semula)} skill (tidak menyusut)")
    print("  memory    : kekal")
    print("  max_tokens: %d, reasoning_effort: tiada" % mt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
