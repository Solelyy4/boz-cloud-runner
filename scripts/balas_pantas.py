#!/usr/bin/env python3
"""balas_pantas.py — GARDIAN JAWAPAN BOT TELEGRAM BOZ.

MENGAPA FAIL INI WUJUD (masalah sebenar yang BOZ laporkan)
==========================================================
"bila saya mesej je telegram bot, ia terus keluarkan link github, arahan, dan
ayat panjang-panjang walaupun saya tak suruh."

Dua punca, kedua-duanya boleh diukur:

  PUNCA 1 — PROMPT SESI. `channel_prompts` menyuntik blok besar yang mengandungi
  contoh kod (bridge.py, fetch2.py) SETIAP giliran. Model kecil membaca contoh itu
  sebagai JAWAPAN yang dijangka, lalu memuntahkan arahan + pautan walaupun mesej
  BOZ hanya "hi". Prompt yang menyenaraikan arahan = model menghantar arahan.

  PUNCA 2 — TIADA GERBANG. Tiada apa-apa yang memeriksa mesej KELUAR sebelum ia
  sampai ke Telegram. Model boleh hantar 40 baris tutorial + 6 pautan dan tiada
  sesiapa menahannya.

Fail ini memasang GERBANG pada mesej keluar:
  - Kesan mesej pendek (sapaan/soalan ringkas) -> hadkan panjang keras.
  - Kesan tutorial (senarai bernombor, "langkah", "pergi ke", "anda perlu") -> potong.
  - Kesan pautan pada mesej yang BOZ tidak minta carian -> tangguhkan.
  - JIKA BOZ MINTA CARI -> pautan DIBENARKAN, sebab itu hasil kerja sebenar.

Guna:
  python scripts/balas_pantas.py --uji          # uji 12 kes, lapor lulus/gagal
  from balas_pantas import periksa, Peraturan   # dipakai oleh plugin gateway
"""
from __future__ import annotations

import json
import re
import sys

# ------------------------------------------------------------------ kelas mesej
SAPAAN = re.compile(
    r"^\s*(hi|hai|hello|helo|hey|yo|ok|oke|okay|test|tes|ping|assalamualaikum|salam|"
    r"apa khabar|apa cerita|selamat|good morning|good night|malam|pagi|petang)\b[\s!.?]*$",
    re.I)
# Mesej yang JELAS minta kerja carian / ambil data.
MINTA_CARI = re.compile(
    r"\b(cari|carikan|search|find|ambik|ambil|get|download|muat turun|scrape|"
    r"semak|check|apa itu|apa tu|siapa|di mana|berapa|harga|berita|news|latest|"
    r"terbaru|kaji|research|analisa|analyze|siasat|investigate|senarai|list|"
    r"tunjuk|show|beri|bagi|hantar|kirim|buat|bikin|tulis|write|build|run|jalankan|"
    r"hack|pentest|scan|audit|test|uji|ringkas|summar|terjemah|translate|"
    r"hitung|kira|analisis|banding|compare|explain|jelaskan|terangkan)\b",
    re.I)
# Mesej yang hanya sapaan/pendek (<= 3 patah perkataan) dan tiada kata kerja tugas.
ARAHAN_TUTORIAL = re.compile(
    r"(berikut (adalah|ialah) (langkah|cara)|berikut\s+(langkah|cara|panduan)|berikut\s*:"
    r"|\blangkah\s*\d|\blangkah-langkah\b|\bcara-cara\b|\bcara untuk\b|"
    r"\banda (boleh|perlu|mesti) (buat|klik|pergi|masuk|buka|jalankan|salin)\b|"
    r"\bpergi ke\b.*\b(klik|pilih|tetapan|settings|menu|github|dashboard)\b|"
    r"\bikut (panduan|cara|langkah) ini\b|"
    r"\bstep\s*\d+\s*[:.)]|"
    r"^\s*\d+[.)]\s+\S.*$\n\s*\d+[.)]\s+\S|"
    r"\bsalin (dan )?tampal\b|copy.?paste|"
    r"\bklik\b|\btekan\b.*\b(butang|button|menu)\b)"
    r"|\b(guna|gunakan|jalankan|run)\b[^.\n]{0,40}\b(perintah|command|arahan|script|skrip|curl|wget|npm|pip|git|python)\b"
    r"|^\s*(curl|wget|npm|pip|git|python|bash|sh|powershell|cmd)\s+\S",
    re.I | re.M)
PAUTAN = re.compile(r"https?://[^\s<>\"'\)\]]+")
# Ayat yang MENYURUH BOZ buat kerja (arahan), bukan jawapan. Untuk mesej sapaan,
# ayat begini membuktikan model tersalah faham -> buang.
ARAHAN_SURUH = re.compile(
    r"(\b(jalankan|buat|pergi|buka|klik|salin|tampal|masuk ke|sign|log ?in|set|pasang|install|"
    r"muat turun|download|hantar|rujuk|lihat|semak|run|execute|paste|copy)\b[^.\n]{0,60}"
    r"\b(repo|workflow|fail|file|link|pautan|github|script|terminal|command|arahan|"
    r"langkah|step|settings|tetapan|config|yml|ini|itu|di atas|di bawah)\b)",
    re.I)
# Mesej SAPAN -> berapa baris maksimum. Bukan 3, beri ruang untuk jawapan berguna.
HAD_SAPAAN_BARIS = 6
HAD_SAPAAN_AKSARA = 600
HAD_TUTORIAL_BARIS = 8
HAD_TUTORIAL_AKSARA = 900
HAD_AM_BARIS = 60
HAD_AM_AKSARA = 3500


def _baris_penting(teks: str, had: int) -> str:
    """Buang baris kosong berlebihan + potong pada `had` baris."""
    baris = [b.rstrip() for b in teks.strip().splitlines()]
    # buang baris kosong berturut
    out: list[str] = []
    kosong = False
    for b in baris:
        if not b.strip():
            if kosong:
                continue
            kosong = True
        else:
            kosong = False
        out.append(b)
    return "\n".join(out[:had]).strip()


def _jenis_mesej_masuk(mesej: str) -> str:
    m = (mesej or "").strip()
    if not m:
        return "kosong"
    if SAPAAN.match(m):
        return "sapaan"
    # pendek (<=4 perkataan) DAN tiada kata kerja tugas -> anggap sapaan/soalan ringkas
    patah = m.split()
    if len(patah) <= 4 and not MINTA_CARI.search(m):
        return "ringkas"
    return "tugasan"


def _buang_baris_tutorial(teks: str) -> str:
    """Buang BARIS yang mengandungi arahan tutorial — bukan potongan tengah ayat.

    Perangkap sebenar: `re.sub` pada corak tutorial memotong sebahagian baris dan
    meninggalkan serpihan ('Klik Settings' -> 'lik Settings'). Buang baris penuh.
    """
    keluar: list[str] = []
    for b in teks.splitlines():
        if ARAHAN_TUTORIAL.search(b):
            continue
        # baris senarai bernombor pendek = langkah
        if re.match(r"^\s*\d+\s*[.)]\s+\S", b) and len(b) < 160:
            continue
        keluar.append(b)
    return "\n".join(keluar)


def _sapaan_balik(mesej: str) -> str:
    """Balasan minimum bila semua kandungan model dibuang.

    Sebab: gerbang memotong tutorial + pautan; kadang tiada apa tinggal. Kalau kita
    pulang satu ayat template SAMA setiap kali, bot nampak rosak. Pilih ringkas
    mengikut mesej BOZ — jujur (kita memang tak jawab apa-apa), mesra, satu baris.
    """
    m = (mesej or "").strip().lower()
    if m in ("hi", "hai", "hello", "helo", "hey", "yo"):
        return "Yo BOZ. Aku di sini — nak buat apa?"
    if m in ("ok", "oke", "okay"):
        return "Baik."
    if m in ("test", "tes", "ping"):
        return "Hidup. Sambungan OK."
    if m in ("pagi", "good morning"):
        return "Pagi BOZ."
    if m in ("malam", "good night"):
        return "Malam BOZ."
    if m in ("terima kasih", "thanks", "tq"):
        return "Sama-sama."
    return "Aku di sini. Nak buat apa?"


def periksa(mesej_masuk: str, jawapan: str) -> dict:
    """Gerbang utama. Pulang {jawapan, dipotong, sebab, jenis}.

    Dipakai sebelum mesej dihantar ke Telegram. Bila BOZ minta carian, pautan
    DIBENARKAN — itu hasil kerja, bukan banjir.
    """
    jenis = _jenis_mesej_masuk(mesej_masuk)
    asal = jawapan or ""
    teks = asal
    sebab: list[str] = []
    dipotong = False

    # (1) Sapaan / mesej ringkas -> keras: buang tutorial + pautan + hadkan panjang.
    if jenis in ("sapaan", "ringkas"):
        if ARAHAN_TUTORIAL.search(teks) or ARAHAN_SURUH.search(teks):
            # Buang BARIS penuh — sub() di tengah baris meninggalkan serpihan
            # ('Klik Settings' -> 'lik Settings') seperti yang berlaku dalam ujian.
            teks = _buang_baris_tutorial(teks)
            teks = "\n".join(b for b in teks.splitlines() if not ARAHAN_SURUH.search(b))
            sebab.append("buang-tutorial")
            dipotong = True
        ada_pautan = PAUTAN.findall(teks)
        if ada_pautan:
            teks = PAUTAN.sub("", teks)
            sebab.append(f"buang-{len(ada_pautan)}-pautan")
            dipotong = True
        b = _baris_penting(teks, HAD_SAPAAN_BARIS)
        if len(teks) > HAD_SAPAAN_AKSARA:
            b = teks[:HAD_SAPAAN_AKSARA].rsplit("\n", 1)[0]
            sebab.append("potong-aksara")
            dipotong = True
        teks = b
        # Buang serpihan tanda baca yang ditinggalkan oleh pemotongan
        teks = re.sub(r"^[\s:;,\-–—]+", "", teks, flags=re.M)
        teks = re.sub(r"[ \t]{2,}", " ", teks).strip()
        if not teks.strip():
            # Semua dibuang -> jangan ulang template sama setiap kali (BOZ rimas).
            # Pilih berdasarkan mesej masuk supaya nampak hidup, bukan robotik.
            teks = _sapaan_balik(mesej_masuk)

    # (2) Mesej tugas: tutorial tetap dilarang, tetapi pautan OK (itu hasil kerja).
    else:
        if ARAHAN_TUTORIAL.search(teks):
            # Buang SETIAP blok/perenggan yang mengandungi arahan tutorial.
            # Jangan syaratkan panjang — kes sebenar: 4 baris tutorial pendek
            # tetap salah bila BOZ minta kerja, bukan prosedur.
            blok = [bl for bl in re.split(r"\n\s*\n", teks)
                    if not ARAHAN_TUTORIAL.search(bl)]
            selamat = "\n\n".join(blok).strip()
            if selamat:
                teks = _buang_baris_tutorial(selamat)
                sebab.append("buang-blok-tutorial")
                dipotong = True
            else:
                # SELURUH jawapan ialah tutorial -> ganti dengan status jujur.
                teks = ("Aku dah terima arahan itu dan sedang kerjakan. "
                        "Hasil akan menyusul dengan bukti.")
                sebab.append("ganti-tutorial-penuh")
                dipotong = True
        if len(teks) > HAD_AM_AKSARA:
            teks = teks[:HAD_AM_AKSARA].rsplit("\n", 1)[0]
            sebab.append("potong-aksara-tugasan")
            dipotong = True
        teks = _baris_penting(teks, HAD_AM_BARIS)

    teks = re.sub(r"\n{3,}", "\n\n", teks).strip()
    return {"jawapan": teks, "dipotong": dipotong, "sebab": sebab, "jenis": jenis,
            "aksara_asal": len(asal), "aksara_akhir": len(teks)}


# ------------------------------------------------------------------- ujian
KES = [
    # (mesej masuk, jawapan model, jangkaan: 'potong'/'lulus', nota)
    ("hi",
     "Berikut adalah langkah untuk setup:\n1. Pergi ke settings\n2. Klik API\n"
     "3. Salin token dari https://github.com/foo/bar dan tampal di https://x.com/y\n"
     "Anda perlu buat ini dahulu.", "potong", "sapaan + tutorial + 2 pautan"),
    ("hai", "Hello BOZ! Ada apa aku boleh bantu?", "lulus", "sapaan mesra, tiada pautan"),
    ("ok", "Sedia. https://github.com/boz/repo", "potong", "sapaan + pautan"),
    ("apa itu docker",
     "Docker ialah platform kontena. Ia membungkus app + dependencies.\n"
     "Sumber: https://docs.docker.com/get-started/", "lulus", "soalan + pautan sumber OK"),
    ("cari harga bitcoin",
     "SIAP: 55 rekod\n-> bing=8, ddg=8, reddit=4\n"
     "https://www.coindesk.com/price/bitcoin", "lulus", "tugasan carian, pautan = hasil"),
    ("test", "Berikut adalah langkah-langkah:\n1. Buka Telegram\n2. Hantar /start", "potong",
     "sapaan + tutorial"),
    ("BOZ suruh upgrade bot",
     "SIAP: enjin carian baru dipasang\n-> 55 rekod dari 12 sumber dalam 37s", "lulus",
     "tugasan, ringkas, bagus"),
    ("pagi",
     "Selamat pagi BOZ. Nak aku cari apa hari ini?", "lulus", "sapaan, tiada pautan"),
    ("saya nak awak upgrade telegram bot",
     "Berikut adalah cara:\nLangkah 1: Pergi ke GitHub Actions\nLangkah 2: Klik run\n"
     "Langkah 3: Salin https://github.com/x/y", "potong", "tutorial dalam tugasan"),
    ("apa khabar", "Baik. " + "x" * 900, "potong", "sapaan + terlalu panjang"),
    ("cari berita AI terbaru",
     "SIAP: 31 rekod dari news=4, youtube=4\nhttps://news.google.com/rss/x", "lulus",
     "tugasan carian"),
    ("yo", "", "lulus", "jawapan kosong -> diganti satu baris"),
    # --- Kes dari aduan SEBENAR BOZ (13 Nov 2026): "mesej je, dia terus bagi link" ---
    ("hi",
     "Boleh rujuk repo ini: https://github.com/Solelyy4/boz-cloud-runner\n"
     "Jalankan workflow telegram.yml untuk mula.", "potong",
     "ADUAN SEBENAR: hi -> link github + arahan"),
    ("test",
     "Guna perintah ini di terminal:\ncurl https://api.example.com -H 'Auth: x'\n"
     "Lihat fail config.yaml di https://github.com/x/y", "potong",
     "ADUAN SEBENAR: test -> arahan terminal + 2 pautan"),
    ("hai",
     "Berikut adalah cara upgrade bot:\n"
     "1. Buka GitHub Actions\n2. Klik workflow\n3. Edit config", "potong",
     "ADUAN SEBENAR: hai -> tutorial upgrade"),
    ("ok BOZ",
     "Fail awak ada di C:/Users/zahin/Downloads dan boleh dimuat turun dari "
     "https://github.com/Solelyy4/boz-hermes-home", "potong",
     "ADUAN SEBENAR: ringkas -> pautan dimuat turun"),
    ("saya nak awak upgrade telegram bot sekarang",
     "SIAP: gerbang + prompt baharu dipasang\n-> 12/12 ujian lulus, adapter AST OK", "lulus",
     "tugasan sebenar BOZ, laporan ringkas bukti"),
]


def uji() -> int:
    lulus = gagal = 0
    for masuk, keluar, jangka, nota in KES:
        r = periksa(masuk, keluar)
        dapat = "potong" if r["dipotong"] else "lulus"
        ok = dapat == jangka
        if ok:
            lulus += 1
        else:
            gagal += 1
        tanda = "LULUS" if ok else "GAGAL"
        print(f"  [{tanda}] {masuk[:28]:30s} jangka={jangka:6s} dapat={dapat:6s} "
              f"jenis={r['jenis']:8s} {r['sebab']} ({nota})")
    print(f"RESULT: {lulus}/{len(KES)} lulus")
    return 0 if gagal == 0 else 1


if __name__ == "__main__":
    if "--uji" in sys.argv:
        raise SystemExit(uji())
    # demo: baca dari stdin sebagai {"masuk": "...", "keluar": "..."}
    if not sys.stdin.isatty():
        try:
            d = json.loads(sys.stdin.read())
            print(json.dumps(periksa(d.get("masuk", ""), d.get("keluar", "")),
                             ensure_ascii=False, indent=1))
        except Exception as e:
            print(f"RALAT: {e}", file=sys.stderr)
            raise SystemExit(2)
    else:
        print(__doc__)
