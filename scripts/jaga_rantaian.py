#!/usr/bin/env python3
"""jaga_rantaian.py — peronda rantaian model semasa bot HIDUP.

MENGAPA: bot BOZ pernah mati berjam-jam kerana rantaian fallback reput — model
pertama pulang 429, sandaran berikut juga mati, dan tiada siapa tahu. Gerbang
`ladang_model.py` menyelesaikan ini SEBELUM bot mula, tetapi model boleh mati
TENGAH JALAN (had dicapai, provider down). Skrip ini memantau semasa berjalan.

CARA: setiap KitaranDetik, uji rantaian yang SAMA seperti config bot. Kalau teraju
gagal tetapi sandaran hidup, tulis laporan JELAS ke log dan (pilihan) beritahu BOZ.
Ia TIDAK mengubah config secara langsung — menulis config ketika gateway sedang
membacanya boleh menyebabkan config rosak. Laporan dahulu, tindakan kemudian.

Guna:
  python scripts/jaga_rantaian.py                 # sekali sahaja
  python scripts/jaga_rantaian.py --loop 600      # setiap 10 minit, tanpa henti
  python scripts/jaga_rantaian.py --beritahu      # hantar ke Telegram bila teraju mati
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

TIMEOUT = 45
# UA browser WAJIB untuk Tokenomix (lihat komen di panggilan curl). Cloudflare
# membalas `403 error code: 1010` kepada UA curl lalai, dan ralat itu dipaparkan
# sebagai `Invalid API key` -- menyalahkan kunci yang betul.
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


ALAT = [{
    "type": "function",
    "function": {
        "name": "terminal", "description": "shell",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
}]


def _hurai(teks: str) -> dict | None:
    """Hurai respons 9Router.

    PEPIJAT SEBENAR (diukur 8 Nov 2026): 9Router menyambung `data: [DONE]` pada
    HUJUNG JSON penuh walaupun bukan streaming:

        {...\"content\":\"\"}}]}data: [DONE]\\n\\n

    `json.loads` penuh gagal dengan "Extra data: line 1 column 543". Versi lama
    terus pulang None -> model SIHAT dilaporkan MATI dan peronda menangis palsu.
    """
    teks = (teks or "").strip()
    if not teks:
        return None
    # Buang ekor SSE dahulu — ini kes 9Router yang paling kerap.
    if "data: [DONE]" in teks:
        teks = teks.split("data: [DONE]")[0].strip()
    if not teks:
        return None
    # Bentuk SSE sebenar: baris bermula `data: {...}`
    if teks.startswith("data:"):
        for b in teks.split("\n"):
            b = b.strip()
            if b.startswith("data:") and "[DONE]" not in b:
                try:
                    return json.loads(b[5:].strip())
                except Exception:
                    pass
        return None
    try:
        return json.loads(teks)
    except Exception:
        return None


def baca_rantaian(config_path: str) -> list[tuple[str, str, str, str]]:
    """Pulang [(provider, base_url, model)] dari config. Kosong jika yaml tiada."""
    try:
        import yaml
    except ImportError:
        print("[AMARAN] PyYAML tiada — tidak dapat baca config", file=sys.stderr)
        return []
    try:
        d = yaml.safe_load(open(config_path, encoding="utf-8"))
    except Exception as e:
        print(f"[AMARAN] config tidak dapat dibaca: {e}", file=sys.stderr)
        return []
    prov = d.get("providers") or {}
    hasil = []
    m = d.get("model") or {}
    p0 = m.get("provider")
    if p0 and m.get("default"):
        pc = prov.get(p0) or {}
        hasil.append((p0, pc.get("base_url", ""), m["default"], pc.get("api_key_env", "")))
    for f in d.get("fallback_model") or []:
        p = f.get("provider")
        pc = prov.get(p) or {}
        hasil.append((p, pc.get("base_url", ""), f.get("model"), pc.get("api_key_env", "")))
    return [h for h in hasil if all(h[:3])]


def uji(base: str, kunci: str, model: str, keyless: bool = False) -> tuple[bool, str]:
    payload = {
        "model": model,
        # max_tokens >=200 WAJIB: gpt-oss pulang content kosong jika kecil.
        "max_tokens": 600,
        "tools": ALAT,
        "messages": [{"role": "user", "content": "Guna alat terminal untuk senarai fail."}],
    }
    # KILO (dan sesetengah gateway keyless lain) menolak token dummy dengan
    # `INVALID_TOKEN`, tetapi menerima permintaan TANPA header Authorization.
    # Diukur 11 Nov 2026: dengan `Bearer Keyless_dummy` -> INVALID_TOKEN;
    # tanpa header -> 200 jawapan penuh. Jadi untuk provider keyless kita
    # hantar permintaan tanpa header, bukan dengan kunci palsu.
    hujung = ["-H", "Content-Type: application/json"]
    if not keyless:
        hujung = ["-H", "Authorization: Bearer " + kunci] + hujung
    try:
        r = subprocess.run(
            ["curl", "-4", "-s", "-m", str(TIMEOUT), "-X", "POST", f"{base}/chat/completions",
             # UA browser WAJIB untuk Tokenomix: Cloudflare membalas `403 error code:
             # 1010` kepada UA curl lalai, dan gateway memaparkannya sebagai
             # `Invalid API key` -- menyalahkan kunci yang sebenarnya betul.
             # Diukur 9 Nov 2026: tanpa baris ini SEMUA 5 model tokenomix dilaporkan
             # MATI sementara panggilan terus dari laptop pulang 200.
             "-H", f"User-Agent: {UA_BROWSER}",
             *hujung,
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=TIMEOUT + 15,
        )
        d = _hurai(r.stdout)
    except Exception as e:
        return False, f"{type(e).__name__}"
    if not d:
        return False, "tiada respons"
    if "error" in d:
        return False, str(d["error"])[:60]
    butir = d.get("choices")
    if not butir:
        return False, "tiada choices"
    ch = butir[0].get("message") or {}
    # LULUS jika model MEMANGGIL alat (bukti tool-calling bot) ATAU menjawab
    # dengan teks yang munasabah. Sebelum ini hanya tool_calls dikira lulus,
    # jadi model yang menjawab betul tanpa memanggil alat dilaporkan MATI
    # (mistral-small-2603: "tiada choices"/"tiada tool_calls" palsu).
    if ch.get("tool_calls"):
        return True, "ok (tool_calls)"
    kandungan = (ch.get("content") or "").strip()
    if len(kandungan) >= 2:
        return True, "ok (teks)"
    return False, "respons kosong"


def kunci_untuk(provider: str, api_key_env: str = "") -> str:
    # DIUKUR 9 Nov 2026: `provider` yang tiada dalam peta jatuh ke lalai
    # MISTRAL_API_KEY. Selepas teraju ditukar ke tokenomix, peronda menghantar
    # KUNCI MISTRAL ke api.tokenomixai.com lalu melaporkan `Invalid API key`
    # pada kelima-lima model -- seolah-olah kunci Tokenomix rosak, sedangkan
    # kunci itu betul (uji-tokenomix.yml dari runner: 26 model tersedia).
    # Lalai mesti provider itu SENDIRI, dan kegagalan mesti ketara.
    #
    # KEYLESS (freeai / blockrun / kilo / nafimods): config menyatakan
    # `api_key_env: KEYLESS_DUMMY` atau `''`. Sebelum ini peronda mengabaikan
    # medan itu dan mencari FREEAI_API_KEY/BLOCKRUN_API_KEY yang memang tidak
    # wujud -> keempat-empat provider dilaporkan "kunci tiada" lalu dikira MATI,
    # padahal ia berfungsi tanpa kredensial. Bot BOZ nampak "SEMUA MATI" dan
    # gagal menjawab, walaupun rangkaiannya sihat.
    # Hormati api_key_env dahulu; jika kosong/tiada, cuba KEYLESS_DUMMY.
    nama_calon = []
    if api_key_env and api_key_env.strip():
        nama_calon.append(api_key_env.strip())
    nama_calon.append(provider.upper().replace("-", "_") + "_API_KEY")
    nama_calon.append("KEYLESS_DUMMY")  # penanda "tiada kredensial diperlukan"

    peta = {
        "groq": "GROQ_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "tokenomix": "TOKENOMIX_API_KEY",
        "9router": "ROUTER9_API_KEY",
        "9router-laptop": "ROUTER9_API_KEY",
        "9router-vps": "ROUTER9_API_KEY",
    }
    if provider in peta:
        nama_calon.insert(0, peta[provider])

    home = os.environ.get("LOCALAPPDATA", "") + r"\hermes" if os.name == "nt" else os.path.expanduser("~/AppData/Local/hermes")

    for nama in nama_calon:
        v = os.environ.get(nama, "").strip()
        if v:
            return v
        if nama == "ROUTER9_API_KEY":
            p = os.path.join(home, "secrets", "9router_key.txt")
            if os.path.exists(p):
                return open(p, encoding="utf-8").read().strip()
            continue
        p = os.path.join(home, ".env")
        if os.path.exists(p):
            for baris in open(p, encoding="utf-8", errors="replace"):
                baris = baris.strip()
                if baris.startswith(nama + "="):
                    return baris.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def satu_pusingan(config_path: str, beritahu: bool) -> int:
    rantaian = baca_rantaian(config_path)
    if not rantaian:
        print("[FAIL] tiada rantaian boleh dibaca", file=sys.stderr)
        return 2

    status = []
    for prov, base, model, ake in rantaian:
        kunci = kunci_untuk(prov, ake)
        # Provider keyless: tiada kredensial sebenar. Jangan hantar token dummy
        # sebagai `Bearer` -- sesetengah gateway (kilo) membalas INVALID_TOKEN.
        keyless = (not kunci) or kunci == os.environ.get("KEYLESS_DUMMY", "\x00")
        if not kunci and not keyless:
            status.append((prov, model, False, "kunci tiada"))
            continue
        ok, sebab = uji(base, kunci, model, keyless=keyless)
        status.append((prov, model, ok, sebab))

    # Tanda: teraju gagal? Ada sandaran hidup?
    teraju_ok = status[0][2]
    sandaran_hidup = [s for s in status[1:] if s[2]]

    print(f"=== JAGA RANTAIAN {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    for prov, model, ok, sebab in status:
        print(f"  [{'HIDUP' if ok else 'MATI '}] {prov:12s} {model:26s} {sebab}")

    if teraju_ok:
        print("RESULT: teraju sihat")
        return 0
    if sandaran_hidup:
        print(f"RESULT: TERAJU MATI — {len(sandaran_hidup)} sandaran hidup, bot masih menjawab")
        if beritahu:
            _beritahu(
                f"TERAJU MATI: {status[0][1]} ({status[0][3]}).\n"
                f"Bot masih hidup melalui: {', '.join(s[1] for s in sandaran_hidup)}.\n"
                f"Jalankan ladang_model.py untuk susun semula rantaian."
            )
        return 1
    print("RESULT: SEMUA MATI — bot TIDAK dapat menjawab", file=sys.stderr)
    if beritahu:
        _beritahu("SEMUA MODEL MATI — bot tidak dapat menjawab. Semak kunci/had provider.")
    return 2


def _beritahu(teks: str) -> None:
    """Hantar ke Telegram BOZ. Senyap jika token tiada (jangan bunuh peronda)."""
    tok_p = os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes", "secrets", "telegram_bot_token.real")
    if not os.path.exists(tok_p):
        return
    tok = open(tok_p, encoding="utf-8").read().strip()
    subprocess.run(
        ["curl", "-4", "-s", "-m", "20", "-X", "POST",
         f"https://api.telegram.org/bot{tok}/sendMessage",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"chat_id": "8043910371", "text": f"[RONDA] {teks}"})],
        capture_output=True, text=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", nargs="?", default="config.yaml")
    ap.add_argument("--loop", type=int, default=0, help="ulang setiap N detik (0 = sekali)")
    ap.add_argument("--beritahu", action="store_true")
    args = ap.parse_args()

    if not args.loop:
        return satu_pusingan(args.config, args.beritahu)
    rc = 0
    while True:
        try:
            rc = satu_pusingan(args.config, args.beritahu)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"[AMARAN] pusingan gagal: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())
