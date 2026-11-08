---
name: cari-luar-telegram
description: "Use when a task needs data from outside Telegram (websites, social media, APIs)."
version: 2.0.0
author: BOZ + BOZ-AGENT
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [web, scrape, social, research, external]
    auto_load: true
---

# CARI LUAR — bot mesti dapatkan data dunia sebenar

Bot Telegram BOZ BUKAN chatbot tertutup. Bila BOZ minta "cari", "dapatkan", "ambil dari",
"download", "semak website", "apa kata X di Twitter/IG/Reddit" — bot MESTI keluar dan ambil data
sebenar, bukan jawab dari ingatan.

## §0 PEMACU DETERMINISTIK — guna ini dulu (paling penting)

Model kecil (8b/14b) TIDAK boleh dipercayai merancang gelung berbilang langkah. Ia berhenti
selepas 1-2 alat atau mencipta gelung. **Satu arahan terminal menjalankan keseluruhan carian:**

```bash
python "$HERMES_HOME/../scripts/fetch.py" "<kata kunci>" --kira 10 --extract 3
python scripts/fetch.py "harga bitcoin" --kira 8
python scripts/fetch.py "python asyncio" --extract 5
python scripts/fetch.py --reddit python --limit 50
python scripts/fetch.py --hn --limit 30
```

Ia buat SEMUA ini sendiri dan tulis fail:
- Carian DuckDuckGo HTML (keyless) + fallback Hacker News
- Ambil kandungan penuh N pautan teratas (direct → r.jina.ai → archive)
- Reddit melalui `.rss` (JSON API 403, .rss 200)
- Tulis `cari/hasil.json` + cetak ringkasan `SIAP: ... — N rekod`

**Aliran kerja bot yang betul (JANGAN guna 5+ panggilan alat):**
1. `terminal`: jalankan `fetch.py` (1 panggilan)
2. Baca ringkasan stdout (sudah ada hasil + pautan)
3. Balas 2-3 baris mengikut SOUL §0.0.1 (SIAP: ... + hasil)

Kalau BOZ minta fail: `MEDIA:<laluan penuh cari/hasil.json>`.

## §1 Tangga alat (untuk kerja ad-hoc bila fetch.py tidak sesuai)

| # | Alat | Bila | Nota |
|---|---|---|---|
| 1 | `terminal` + `fetch.py` | **Utama** — carian, extract, reddit, HN | Deterministik, 1 panggilan |
| 2 | `web_search` | Carian ad-hoc pantas | DDGS keyless di cloud |
| 3 | `web_extract` | Baca 1-2 halaman terus | PDF/artikel |
| 4 | `terminal` + `curl` | API JSON, endpoint terus | Pure-HTTP dulu |
| 5 | `browser_exec` | Halaman perlu JS/login/klik | Chromium ada dalam runner |
| 6 | `vision_analyze` | Baca imej/screenshot | — |

**Larangan:** jangan sekali-kali reka data. Kalau alat gagal semua, lapor "TERHALANG: " + sebab
teknikal. Jangan isi dengan andaian.

## §2 Media sosial — laluan yang DISAHKAN pada 5 Nov 2026

| Sasaran | Laluan yang JALAN | Yang GAGAL (jangan cuba) |
|---|---|---|
| **Reddit** | `https://www.reddit.com/r/SUB/hot/.rss` (HTTP 200) | `.json` → **403**; HTML scrape → 403 |
| **Hacker News** | `https://hn.algolia.com/api/v1/search?query=` | — |
| **X/Twitter** | `browser_exec` + tunggu `article`; atau mirror nitter | API berbayar |
| **Instagram** | `?__a=1&__d=dis` atau `browser_exec` scroll | HTML mentah |
| **YouTube** | `yt-dlp --dump-json` | Scrape watch page |
| **TikTok** | `browser_exec` + `window.__UNIVERSAL_DATA` | HTML statik |
| **Bluesky** | `https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=` | — |

Reddit `.rss` pulangkan Atom XML — parse dengan regex `<entry>...</entry>`, ambil `<title>`,
`<link href=...>`, `<updated>`. **Header `Accept: application/rss+xml` membantu.**

User-Agent mozek Chrome 131 wajib. UA lalai `python-urllib` disekat serta-merta.

## §3 Tangga bila disekat (jangan berhenti pada 403)

`403/429` → tukar UA + `Accept-Language` → `.rss`/`.json` alternatif → `r.jina.ai/<url>` sebagai
proksi baca → `web.archive.org/save/<url>` → `browser_exec` (Chromium sebenar) → `curl_cffi`
(TLS JA3, kalau dipasang).

Cloudflare + Turnstile → `browser_exec`, bukan `curl`.

**Jangan ulang permintaan identik.** Kalau satu laluan 403, tukar laluan pada cubaan pertama.

## §4 Simpan hasil (jangan banjiri chat)

`fetch.py` sudah menulis `cari/hasil.json`. Untuk kerja tersuai:

```python
import json, pathlib
out = pathlib.Path("cari"); out.mkdir(exist_ok=True)
(out / "hasil.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"{len(items)} rekod -> cari/hasil.json")
```

Bila BOZ minta fail: hantar `MEDIA:/laluan/penuh`. Di Telegram, fail kekal dalam runner —
naikkan ke repo peribadi atau pulangkan ringkasan + 5 sampel.

## §5 Format laporan

Ikut SOUL §0.0.1 — maksimum 3 baris.

Selesai → dua baris: `SIAP: ` + apa yang dicari + ` — ` + jumlah rekod. Baris kedua:
`-> ` + sumber utama + ` | ` + 5 sampel ringkas.

Kalau BOZ minta fail: `SIAP: ` + jumlah rekod, kemudian `MEDIA:/laluan`.
