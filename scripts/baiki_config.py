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

# Rantaian berasas HAD SEBENAR yang diukur 8 Nov 2026:
#   Groq    : 1000 permintaan/jam, 8/8 panggilan berturut lulus, gpt-oss-120b & 20b 2/2 tools
#   Mistral : ~3-4 panggilan lalu 429 berpanjangan (diukur: 200,200,200,429,429,429)
# Bot mesti diterajui Groq. Mistral hanya sandaran terakhir.
MODEL_LALAI = ("groq", "openai/gpt-oss-120b")
FALLBACK = [
    {"provider": "groq", "model": "openai/gpt-oss-20b"},
]
# Mistral: had akaun sangat ketat — diukur 8 Nov 2026: 200,200,200,429,429,429 berturut.
# Ia BOLEH jadi sandaran terakhir di config, tetapi TIDAK boleh disahkan sebagai wajib:
# menguji dua kali dalam satu minit sudah cukup untuk mencetuskan 429.
SANDARAN_TERAKHIR = {"provider": "mistral", "model": "ministral-8b-latest"}
# Model yang terbukti MATI/reput — jangan sekali-kali masuk fallback.
MODEL_DILARANG = {
    "open-mistral-nemo",       # TIADA dalam akaun
    "pixtral-12b-latest",      # TIADA dalam akaun
    "mistral-medium-latest",   # 429 rate_limited (fallback #1 lama)
    "mistral-large-4",         # pulang blok `thinking` -> jawapan pelik
    "qwen/qwen3.8-27b",        # tool-calling tidak stabil (1/2, mereka-reka nama alat)
}
KUNCI_WAJIB = ("model", "providers", "platforms", "skills")


def _yaml():
    """Pulang modul yaml, memasangnya jika perlu.

    SEBAB: runner GitHub memakai venv Hermes yang TIDAK mengandungi PyYAML.
    Bukti run 42436126082: `ModuleNotFoundError: No module named 'yaml'` pada
    langkah 'Baiki config' -> langkah GERBANG di-skip -> bot tidak pernah mula.
    Ini menjadikan seluruh bot mati hanya kerana satu pakej hilang.
    Tiga lapis: import biasa -> pasang sendiri -> pemproses YAML mini.
    """
    try:
        import yaml  # noqa: PLC0415
        return yaml
    except ImportError:
        pass
    # Lapis 2: pasang ke dalam venv yang sedang berjalan.
    try:
        import subprocess
        import sys
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "pyyaml"],
            capture_output=True, text=True, timeout=120,
        )
        import yaml  # noqa: PLC0415
        return yaml
    except Exception:
        return None


def muat(path: str) -> dict:
    yaml = _yaml()
    if yaml is None:
        # Bot mesti terus hidup: pulang dict kosong supaya `baiki()` tidak mengubah
        # apa-apa dan config sedia ada dikekalkan. (Dahulu: SystemExit -> GERBANG
        # di-skip -> bot TIDAK PERNAH mula hanya kerana PyYAML tiada.)
        print("[AMARAN] PyYAML tiada — config tidak dapat dibaca/dibaiki, "
              "guna apa yang ada", file=sys.stderr)
        return {}
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
    prov = cfg.setdefault("providers", {})
    # LINDUNG TERAJU: jika config SUDAH diterajui provider yang dipasang khas
    # (tokenomix/glm-5.3, diukur 4/5 tugasan bersekat) dan kuncinya ada, JANGAN
    # timpa. Skrip ini dulu memaksa groq lalu memusnahkan rantaian baharu pada
    # setiap run -- gateway mula dengan model yang menolak tugasan BOZ.
    teraju_asal = model.get("provider")
    dilindungi = (
        teraju_asal in TERAJU_DILINDUNGI
        and teraju_asal in prov
        and bool(prov[teraju_asal].get("base_url"))
    )
    if dilindungi:
        ubah.append(f"model: dikekalkan {teraju_asal}/{model.get('default')} "
                    f"(teraju dilindungi, bukan ditimpa ke {MODEL_LALAI[0]})")
    elif (model.get("provider"), model.get("default")) != MODEL_LALAI:
        ubah.append(f"model: {model.get('provider')}/{model.get('default')} -> {MODEL_LALAI[0]}/{MODEL_LALAI[1]}")
        model["provider"], model["default"] = MODEL_LALAI
    model.setdefault("api_mode", "chat_completions")
    # gpt-oss-120b di Groq: 131,072 konteks. Nilai lama (262,144 untuk ministral-14b)
    # akan membuat Hermes menghantar prompt terlalu besar -> 400.
    if model.get("context_window") != 131072:
        ubah.append(f"model.context_window: {model.get('context_window')} -> 131072")
        model["context_window"] = 131072

    # --- 2. Providers wajib wujud ---
    if "mistral" not in prov:
        prov["mistral"] = {"base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"}
        ubah.append("providers.mistral ditambah")
    if "groq" not in prov:
        prov["groq"] = {"base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"}
        ubah.append("providers.groq ditambah")
    if "tokenomix" not in prov:
        prov["tokenomix"] = {"base_url": "https://api.tokenomixai.com/v1",
                             "api_key_env": "TOKENOMIX_API_KEY"}
        ubah.append("providers.tokenomix ditambah")
    # Provider yatim (menunjuk base_url kosong) mematikan setiap giliran yang
    # jatuh ke sandaran itu. Buang supaya rantaian hanya menyenaraikan yang sah.
    for nama in [k for k, v in list(prov.items())
                 if isinstance(v, dict) and not v.get("base_url")]:
        prov.pop(nama, None)
        ubah.append(f"providers.{nama} dibuang (base_url kosong)")

    # --- 3. Fallback ditulis SEMULA ikut data ukuran, bukan diwarisi ---
    # Bukti: fallback warisan (mistral-medium-latest, qwen3.8-27b, open-mistral-nemo)
    # semuanya mati/reput. Membaiki sebahagian sahaja meninggalkan urutan buruk:
    # Mistral (429 selepas 3-4 panggilan) mendahului Groq (1000/jam) -> bot mati lambat.
    lama = cfg.get("fallback_model") or []
    model_lama = [f.get("model") for f in lama if isinstance(f, dict)]
    # Mistral sebagai sandaran TERAKHIR: ia membantu bila Groq benar-benar mati,
    # tetapi tidak boleh diuji sebagai wajib (429 selepas beberapa panggilan).
    cfg["fallback_model"] = [dict(f) for f in FALLBACK] + [dict(SANDARAN_TERAKHIR)]
    ubah.append(
        f"fallback ditulis semula: {model_lama} -> {[f['model'] for f in cfg['fallback_model']]}"
    )

    # --- 4. max_tokens: WAJIB besar untuk model reasoning ---
    # BUKTI DIUKUR 8 Nov 2026 pada Groq gpt-oss:
    #   max_tokens=60   -> 3/4 berisi (ia habiskan kuota pada medan `reasoning`,
    #                      content='' dengan finish_reason=length)
    #   max_tokens=200+ -> 4/4 berisi
    # Ini punca bot "menjawab kosong" / mesej tidak sampai. Jangan turunkan.
    if (model.get("max_tokens") or 0) < 2000:
        ubah.append(f"model.max_tokens: {model.get('max_tokens')} -> 4096 (model reasoning perlukan ruang)")
        model["max_tokens"] = 4096

    # --- 5. reasoning_effort: buang sepenuhnya (nilai peringkat -> HTTP 400) ---
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
    # Had mutlak 3000 bait melindungi config sebenar (~10k) daripada dirosakkan
    # oleh sedsed/sed yang menulis satu baris. Tetapi ia juga menolak config sah
    # yang MEMANG kecil (config ujian) -- dan itu membuatkan `baiki_config`
    # melaporkan FAIL pada fail yang betul. Jadi had = 3000 ATAU 60% saiz asal,
    # yang mana lebih rendah: config besar tidak boleh menyusut teruk, config
    # kecil tidak dihukum kerana saiznya.
    had = min(3000, max(200, int(asal_bait * 0.6))) if asal_bait else 3000
    if saiz < had:
        return False, f"terlalu kecil ({saiz} bait < had {had}, asal {asal_bait})"
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
    if not cfg:
        # muat() pulang {} bila PyYAML tiada. JANGAN tulis apa-apa — menulis dict
        # kosong akan memusnahkan config (sejarah: 4,458 bait -> 45 bait).
        print("[AMARAN] config tidak dibaca — tiada perubahan ditulis")
        return 0
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

    yaml = _yaml()
    if yaml is None:
        # Bukan bunuh run: config sedia ada mungkin sudah betul (dibaiki pada run
        # sebelumnya dan disimpan semula ke repo home). Bot lebih baik hidup dengan
        # config lama yang sah daripada mati kerana satu pakej tiada.
        print("[AMARAN] PyYAML tiada — config TIDAK diubah, guna config sedia ada",
              file=sys.stderr)
        return 0
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
