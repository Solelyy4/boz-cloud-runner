#!/usr/bin/env python3
"""baiki_config.py — baiki config.yaml TANPA memusnahkannya.

KEGAGALAN SEBENAR YANG IA ELAK:
  - `sed` menulis semula config daripada satu pemboleh ubah -> 4,458 bait jadi 45 bait,
    bot hilang providers/skills/platforms dan terus bisu.
  - Model dalam config yang sudah TIADA dalam akaun (open-mistral-nemo,
    pixtral-12b-latest) atau yang pulang 429 (mistral-medium-latest) -> rantai
    fallback reput -> `rebuilt_restart_limit_exceeded` sampai ke Telegram.
  - `agent.reasoning_effort` berperingkat -> HTTP 400 pada model kecil.

PERATURAN (dipatuhi skrip ini):
  1. Salin ke .bak SEBELUM tulis.
  2. Edit dengan YAML parser, bukan sed.
  3. Sahkan saiz + kunci penting SELEPAS tulis; pulih dari .bak kalau rosak.
  4. Kekalkan SEMUA kunci lain (skills.auto_load, channel_prompts, memory, ...).

Guna:
  python scripts/baiki_config.py config.yaml            # baiki di tempat
  python scripts/baiki_config.py config.yaml --dry-run  # tunjuk perubahan sahaja
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

# Model yang DISAHKAN hidup oleh scripts/sah_model.py (8 Nov 2026).
MODEL_LALAI = ("mistral", "ministral-14b-latest")
FALLBACK = [
    {"provider": "mistral", "model": "ministral-8b-latest"},
    {"provider": "groq", "model": "openai/gpt-oss-120b"},
    {"provider": "groq", "model": "qwen/qwen3.8-27b"},
]
# Model yang terbukti MATI/reput — jangan sekali-kali masuk fallback.
MODEL_DILARANG = {
    "open-mistral-nemo",       # TIADA dalam akaun
    "pixtral-12b-latest",      # TIADA dalam akaun
    "mistral-medium-latest",   # 429 rate_limited (fallback #1 lama)
    "mistral-large-4",         # pulang blok `thinking` -> jawapan pelik
}
KUNCI_WAJIB = ("model", "providers", "platforms", "skills")


def muat(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    if not isinstance(d, dict):
        raise SystemExit(f"[FAIL] {path} bukan mapping YAML yang sah")
    return d


def baiki(cfg: dict) -> list[str]:
    """Ubah cfg di tempat. Pulang senarai perubahan untuk log."""
    ubah: list[str] = []

    # --- 1. Rantaian model ---
    model = cfg.setdefault("model", {})
    if (model.get("provider"), model.get("default")) != MODEL_LALAI:
        ubah.append(f"model: {model.get('provider')}/{model.get('default')} -> {MODEL_LALAI[0]}/{MODEL_LALAI[1]}")
        model["provider"], model["default"] = MODEL_LALAI
    model.setdefault("api_mode", "chat_completions")

    # --- 2. Providers wajib wujud ---
    prov = cfg.setdefault("providers", {})
    if "mistral" not in prov:
        prov["mistral"] = {"base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"}
        ubah.append("providers.mistral ditambah")
    if "groq" not in prov:
        prov["groq"] = {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"}
        ubah.append("providers.groq ditambah")

    # --- 3. Fallback bersih ---
    lama = cfg.get("fallback_model") or []
    bersih, dibuang = [], []
    for f in lama:
        if not isinstance(f, dict):
            continue
        m = f.get("model", "")
        if m in MODEL_DILARANG or m == MODEL_LALAI[1]:
            dibuang.append(m)  # reput/mati, atau sekadar ulangan model lalai
            continue
        bersih.append({"provider": f.get("provider"), "model": m})
    if dibuang:
        ubah.append(f"fallback dibuang (mati/reput/ulangan): {dibuang}")
    ada = {f["model"] for f in bersih}
    for f in FALLBACK:
        if f["model"] == MODEL_LALAI[1]:
            continue  # jangan ulang model lalai dalam fallback
        if f["model"] not in ada:
            bersih.append(dict(f))
            ada.add(f["model"])
            ubah.append(f"fallback ditambah: {f['provider']}/{f['model']}")
    cfg["fallback_model"] = bersih

    # --- 4. reasoning_effort: buang sepenuhnya (nilai peringkat -> HTTP 400) ---
    agent = cfg.get("agent") or {}
    re_val = agent.get("reasoning_effort", "<tiada>")
    if re_val not in ("<tiada>", None):
        ubah.append(f"agent.reasoning_effort dibuang (nilai: {re_val})")
        agent.pop("reasoning_effort", None)
        cfg["agent"] = agent

    # --- 5. max_turns munasabah untuk bot sembang ---
    mt = (cfg.get("agent") or {}).get("max_turns")
    if not isinstance(mt, int) or mt < 20 or mt > 120:
        cfg.setdefault("agent", {})["max_turns"] = 60
        ubah.append(f"agent.max_turns: {mt} -> 60")

    # --- 6. Memori cukup besar (memori penuh merosakkan giliran) ---
    mem = cfg.setdefault("memory", {})
    if (mem.get("memory_char_limit") or 0) < 6000:
        mem["memory_char_limit"] = 6000
        ubah.append("memory.memory_char_limit -> 6000")
    if (mem.get("user_char_limit") or 0) < 4000:
        mem["user_char_limit"] = 4000
        ubah.append("memory.user_char_limit -> 4000")

    # --- 7. Aux vision: jangan rujuk model yang tiada ---
    aux = (cfg.get("auxiliary") or {}).get("vision")
    if isinstance(aux, dict) and aux.get("model") in MODEL_DILARANG:
        ubah.append(f"auxiliary.vision dibuang (model {aux.get('model')} TIADA dalam akaun)")
        cfg["auxiliary"].pop("vision", None)

    return ubah


def sahkan(path: str, asal_bait: int) -> tuple[bool, str]:
    """Sahkan fail SELEPAS tulis: boleh parse, saiz munasabah, kunci penting ada."""
    try:
        d = muat(path)
    except Exception as e:
        return False, f"tidak boleh parse: {e}"
    saiz = os.path.getsize(path)
    if saiz < 3000:
        return False, f"terlalu kecil ({saiz} bait, asal {asal_bait})"
    hilang = [k for k in KUNCI_WAJIB if k not in d]
    if hilang:
        return False, f"kunci hilang: {hilang}"
    if not d.get("fallback_model"):
        return False, "fallback_model kosong"
    return True, f"OK ({saiz} bait, asal {asal_bait})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.config):
        print(f"[FAIL] {args.config} tiada", file=sys.stderr)
        return 1
    asal_bait = os.path.getsize(args.config)
    cfg = muat(args.config)
    ubah = baiki(cfg)

    print(f"=== {len(ubah)} perubahan ===")
    for u in ubah:
        print("  -", u)
    if not ubah:
        print("  (tiada — config sudah betul)")
        return 0
    if args.dry_run:
        print("\n[dry-run] tiada fail ditulis")
        return 0

    import yaml
    bak = args.config + ".bak"
    shutil.copy2(args.config, bak)
    print(f"sandaran: {bak}")

    tmp = args.config + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    os.replace(tmp, args.config)

    ok, mesej = sahkan(args.config, asal_bait)
    if not ok:
        shutil.copy2(bak, args.config)
        print(f"[FAIL] pengesahan gagal: {mesej} -> DIPULIH dari .bak", file=sys.stderr)
        return 1
    print(f"[PASS] {mesej}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
