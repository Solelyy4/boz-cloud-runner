#!/usr/bin/env python3
"""ladang_model.py — kumpul (farm) SEMUA model yang hidup, susun rantaian terbaik.

MENGAPA SKRIP INI WUJUD
Bot BOZ mati berulang kali kerana rantaian model reput: model dalam config sudah
TIADA dalam akaun, atau pulang 429 selepas beberapa panggilan. Meneka model sihat
dengan membaca nama tidak berkesan. Satu-satunya cara yang jujur: PANGGIL setiap
model, ukur, dan susun rantaian daripada yang BENAR-BENAR menjawab dengan alat.

CARA IA BEKERJA
  1. Kumpul calon dari SEMUA punca yang BOZ ada:
       - 9Router (laptop + VPS)  -> 32 akaun Mistral di belakang satu endpoint
       - Mistral API terus      -> kunci sendiri
       - Groq API terus         -> 1000 permintaan/jam
  2. Uji setiap calon: sembang, KEMUDIAN tool-calling (bot perlukan alat).
  3. Ukur kestabilan: 5 panggilan berturut. Yang gagal bukan sandaran.
  4. Susun rantaian: kestabilan dahulu, kemudian kelajuan.
  5. Tulis blok rantaian ke config dengan YAML parser + sahkan baca-balik.

NOTA 9ROUTER: ia menghantar `data: [DONE]` walaupun bukan streaming. Parser naif
menganggap respons SAH sebagai rosak (kesilapan sebenar yang membuang masa).
`_hurai()` mengendalikan kedua-dua bentuk.

Guna:
  python scripts/ladang_model.py                    # uji + tunjuk rantaian
  python scripts/ladang_model.py --tulis-config CFG # uji + tulis ke config
  python scripts/ladang_model.py --cepat            # 2 cubaan sahaja (pantas)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

TIMEOUT = 60
JEDA = 0.4  # elak mencetus had sendiri semasa menguji

ALAT = [{
    "type": "function",
    "function": {
        "name": "terminal",
        "description": "Jalankan arahan shell",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
}]

# ---- punca calon ----
SEMBER = [
    # (nama, base_url, env_kunci, senarai_model)
    ("9router-laptop", "http://127.0.0.1:20128/v1", "ROUTER9_API_KEY", [
        "mistral-fast", "mistral-max", "mistral-code",
    ]),
    ("9router-vps", "http://129.221.178.149:20128/v1", "ROUTER9_API_KEY", [
        "mistral-fast", "mistral-max", "mistral-code",
    ]),
    ("groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", [
        "openai/gpt-oss-120b", "openai/gpt-oss-20b",
    ]),
    ("mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", [
        "ministral-8b-latest",
    ]),
]


def _kunci(nama: str) -> str:
    """Ambil kunci dari env, atau dari fail secrets Hermes."""
    v = os.environ.get(nama, "").strip()
    if v:
        return v
    peta = {
        "ROUTER9_API_KEY": ("secrets", "9router_key.txt"),
        "MISTRAL_API_KEY": (".env", "MISTRAL_API_KEY"),
        "GROQ_API_KEY": (".env", "GROQ_API_KEY"),
    }
    folder, fail_atau_kunci = peta.get(nama, (None, None))
    if not folder:
        return ""
    home = os.environ.get("LOCALAPPDATA", "") + r"\hermes" if os.name == "nt" else os.path.expanduser("~/AppData/Local/hermes")
    p = os.path.join(home, folder, fail_atau_kunci)
    if not os.path.exists(p):
        return ""
    if folder == "secrets":
        return open(p, encoding="utf-8").read().strip()
    for baris in open(p, encoding="utf-8", errors="replace"):
        baris = baris.strip()
        if baris.startswith(fail_atau_kunci + "="):
            return baris.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _hurai(teks: str) -> dict | None:
    """Hurai respons. 9Router menyambung `data: [DONE]` walaupun bukan streaming."""
    teks = (teks or "").strip()
    if not teks:
        return None
    if teks.startswith("data:"):
        for b in teks.split("\n"):
            b = b.strip()
            if b.startswith("data:") and "[DONE]" not in b:
                try:
                    return json.loads(b[5:].strip())
                except Exception:
                    pass
        return None
    if "data: [DONE]" in teks:
        teks = teks.split("data: [DONE]")[0].strip()
    try:
        return json.loads(teks)
    except Exception:
        return None


def _curl(url: str, kunci: str, payload: dict) -> str:
    args = ["curl", "-4", "-s", "-m", str(TIMEOUT), "-X", "POST",
            f"{url}/chat/completions",
            "-H", f"Authorization: Bearer {kunci}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload)]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT + 15)
        return r.stdout or r.stderr
    except Exception as e:
        return f'{{"error":{{"message":"{type(e).__name__}: {e}"}}}}'


def uji(base: str, kunci: str, model: str, alat: bool) -> tuple[bool, str, float]:
    """Pulang (lulus, sebab, saat)."""
    import time
    import datetime  # noqa: F401  (kekalkan import ringan)
    payload = {
        "model": model,
        # max_tokens MESTI besar: gpt-oss habiskan kuota kecil pada `reasoning`
        # lalu pulang content kosong (diukur: 60 -> 3/4 gagal).
        "max_tokens": 800,
        "messages": [{"role": "user",
                      "content": "Senaraikan fail dalam folder. Guna alat terminal." if alat
                                 else "Balas satu perkataan: OK"}],
    }
    if alat:
        payload["tools"] = ALAT
    t0 = time.time()
    d = _hurai(_curl(base, kunci, payload))
    saat = round(time.time() - t0, 2)
    if not d:
        return False, "respons tidak dapat dihurai", saat
    if "error" in d:
        return False, str(d["error"])[:70], saat
    try:
        ch = d["choices"][0]["message"]
    except Exception:
        return False, "tiada choices", saat
    if alat:
        return bool(ch.get("tool_calls")), "tool_calls" if ch.get("tool_calls") else "tiada tool_calls", saat
    c = ch.get("content")
    return bool(isinstance(c, str) and c.strip()), (c or "(kosong)")[:30], saat


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tulis-config")
    ap.add_argument("--cepat", action="store_true", help="2 cubaan sahaja")
    ap.add_argument("--keluaran", default="ladang_model.json")
    args = ap.parse_args()

    ulang = 2 if args.cepat else 5
    import time

    calon = []
    print("=== FARMING MODEL ===")
    for nama, base, kenv, senarai in SEMBER:
        kunci = _kunci(kenv)
        if not kunci:
            print(f"[SKIP] {nama}: kunci {kenv} tiada")
            continue
        print(f"\n--- {nama} ({base}) ---")
        for m in senarai:
            ok_s, sebab_s, _ = uji(base, kunci, m, alat=False)
            time.sleep(JEDA)
            if not ok_s:
                print(f"  [MATI] {m:30s} sembang: {sebab_s}")
                continue
            ok_a, sebab_a, saat = uji(base, kunci, m, alat=True)
            time.sleep(JEDA)
            if not ok_a:
                print(f"  [TIADA ALAT] {m:30s} {sebab_a}")
                continue
            # kestabilan
            lulus = 0
            for _ in range(ulang):
                ok, _, _ = uji(base, kunci, m, alat=True)
                lulus += 1 if ok else 0
                time.sleep(JEDA)
            calon.append({
                "sumber": nama, "base": base, "kunci_env": kenv, "model": m,
                "lulus": lulus, "ulang": ulang, "saat": saat,
            })
            print(f"  [HIDUP] {m:30s} {lulus}/{ulang} stabil, {saat}s/panggilan")

    if not calon:
        print("\nRESULT: TIADA MODEL HIDUP — semak kunci dan rangkaian", file=sys.stderr)
        return 1

    # Rantaian: kestabilan dahulu, kemudian kelajuan
    calon.sort(key=lambda c: (-c["lulus"], c["saat"]))
    # buang pendua model sama merentas sumber (kekalkan yang terbaik)
    dilihat, bersih = set(), []
    for c in calon:
        if c["model"] in dilihat:
            continue
        dilihat.add(c["model"]); bersih.append(c)

    print("\n=== RANTAIAN TERBAIK (kestabilan dahulu, kemudian kelajuan) ===")
    for i, c in enumerate(bersih, 1):
        print(f"  {i}. {c['model']:30s} {c['lulus']}/{c['ulang']}  {c['saat']:>5}s  ({c['sumber']})")

    with open(args.keluaran, "w", encoding="utf-8") as f:
        json.dump(bersih, f, indent=2, ensure_ascii=False)
    print(f"\nhasil ditulis: {args.keluaran} ({len(bersih)} model hidup)")

    if args.tulis_config:
        tulis_config(args.tulis_config, bersih)
    return 0


def tulis_config(path: str, rantaian: list[dict]) -> None:
    """Tulis rantaian ke config dengan YAML parser. Sahkan baca-balik."""
    try:
        import yaml
    except ImportError:
        print("[AMARAN] PyYAML tiada — config tidak ditulis", file=sys.stderr)
        return
    if not os.path.exists(path):
        print(f"[FAIL] {path} tiada", file=sys.stderr)
        return
    asal = open(path, encoding="utf-8").read()
    import shutil
    shutil.copy2(path, path + ".ladang.bak")
    d = yaml.safe_load(asal)
    if not isinstance(d, dict):
        print("[FAIL] config bukan mapping", file=sys.stderr)
        return

    teraju = rantaian[0]
    d.setdefault("providers", {})

    def nama_provider(sumber: str) -> str:
        """Peta nama sumber -> nama provider dalam config.

        PEPIJAT SEBENAR: ladang_model menamakan sumber `9router-vps` tetapi config
        mendaftarkan provider sebagai `9router`. Tanpa peta ini, rantaian menunjuk
        provider yang TIDAK WUJUD -> base_url kosong -> sandaran mustahil berfungsi.
        """
        return {"9router-laptop": "9router", "9router-vps": "9router"}.get(sumber, sumber)

    for c in rantaian:
        pn = nama_provider(c["sumber"])
        d["providers"].setdefault(pn, {"base_url": c["base"], "api_key_env": c["kunci_env"]})

    prov = nama_provider(teraju["sumber"])

    d["model"] = {
        "provider": prov,
        "default": teraju["model"],
        "api_mode": "chat_completions",
        "context_window": 131072,
        # >=2000 WAJIB: model reasoning pulang content kosong jika kecil.
        "max_tokens": 8192,
    }
    d["fallback_model"] = [
        {"provider": nama_provider(c["sumber"]), "model": c["model"]} for c in rantaian[1:]
    ]

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(d, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    os.replace(tmp, path)

    # SAHKAN baca-balik — jangan percaya tulis buta
    semula = yaml.safe_load(open(path, encoding="utf-8"))
    prov_sah = set((semula.get("providers") or {}).keys())
    yatim = [
        f for f in (semula.get("fallback_model") or [])
        if f.get("provider") not in prov_sah or not (semula["providers"][f["provider"]].get("base_url"))
    ]
    ok = (semula.get("model", {}).get("default") == teraju["model"]
          and semula.get("model", {}).get("provider") in prov_sah
          and len(semula.get("fallback_model") or []) == len(rantaian) - 1
          and not yatim
          and semula.get("skills", {}).get("auto_load"))
    saiz = os.path.getsize(path)
    if not ok or saiz < 3000:
        shutil.copy2(path + ".ladang.bak", path)
        sebab = f"provider yatim: {yatim}" if yatim else f"saiz {saiz}"
        print(f"[FAIL] pengesahan gagal ({sebab}) -> dipulih dari .bak", file=sys.stderr)
        return
    print(f"[PASS] config ditulis: {path} ({saiz} bait, teraju {teraju['model']}, "
          f"{len(rantaian)-1} sandaran semua provider sah)")


if __name__ == "__main__":
    sys.exit(main())
