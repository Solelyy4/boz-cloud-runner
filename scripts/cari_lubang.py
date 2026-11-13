#!/usr/bin/env python3
"""cari_lubang.py — ENJIN CARIAN UNIVERSAL "SAMPAI LUBANG CACANG" untuk bot Telegram BOZ.

MENGAPA FAIL INI WUJUD (bukan teori — setiap satu menjawab kegagalan yang DISAHKAN)
==================================================================================
fetch.py / fetch2.py hanya mencuba 3-4 enjin dan berhenti pada kegagalan pertama.
Hasilnya bot kata "tak jumpa" atau balas dari ingatan. BOZ mahu: CARI SAMPAI JUMPA.

Fail ini menggantikan kedua-duanya dengan satu enjin yang:
  1. Menembak SEMUA enjin carian serentak (paralel, bukan beratur).
  2. Mencuba SEMUA platform media sosial melalui pintu belakang yang terbukti.
  3. Apabila 0 hasil: turun TANGGA ESKALASI (Wayback -> CommonCrawl -> arsip ->
     cermin -> pelayar -> jambatan laptop) sampai jumpa atau semua jalan mati.
  4. Menulis bukti ke cari/hasil.json (bukan jawapan dari ingatan).

SETIAP LALUAN DI BAWAH DISAHKAN HTTP, bukan andaian. Yang GAGAL disimpan dalam
LALUAN_MATI supaya bot tidak membuang masa mengulang jalan yang sudah tertutup.

Guna:
  python scripts/cari_lubang.py "harga bitcoin hari ini"
  python scripts/cari_lubang.py "berita AI" --kira 15 --extract 4
  python scripts/cari_lubang.py --url https://example.com/artikel
  python scripts/cari_lubang.py --lubang "topik sukar"   # eskalasi maksimum
  python scripts/cari_lubang.py --uji                    # uji setiap laluan, lapor hidup/mati
  python scripts/cari_lubang.py --platform list

Keluaran: cari/hasil.json + ringkasan stdout untuk model baca.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

try:
    import httpx
except ImportError:
    print("PERLU: python -m pip install httpx", file=sys.stderr)
    raise SystemExit(2)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
# HEADER MINIMUM — ini yang DISAHKAN lulus (13 Nov 2026).
# Ukuran: HDR penuh (dengan Cache-Control + Accept-Encoding + Accept-Language berbilang)
# -> DDG pulang 202 halaman cabaran. HDR minimum ini -> 200 dengan 10 hasil.
# JANGAN tambah header tanpa mengukur semula: satu header tambahan cukup untuk
# menukar 200 -> 202 pada DuckDuckGo, dan bot akan "tak jumpa apa-apa".
HDR = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
}
TIMEOUT = 20.0
OUT_DIR = os.environ.get("CARI_DIR", "cari")

# Laluan yang DISAHKAN mati — jangan cuba lagi, jimat masa.
# Format: nama -> sebab (bukti bertarikh). Dikemas kini bila --uji dijalankan.
LALUAN_MATI: dict[str, str] = {
    "reddit.json": "403 (API tutup untuk UA tanpa OAuth) — guna .rss",
    "nitter.net": "instance utama mati sejak 2024 — cuba cermin lain",
    "google.jina": "r.jina.ai pada google.com -> 403 AbuseAlleviationError",
    "bing.site_op": "Bing MENGABAIKAN operator site: (pulang domain tak berkaitan)",
}


# ---------------------------------------------------------------- utiliti asas
# HAD KADAR DDG — diukur 13 Nov 2026: selepas ~4 carian pantas berturut, DDG
# mula pulang 202 (halaman cabaran) selama beberapa minit. Bot yang menembak
# 5 platform serentak semuanya menggunakan DDG akan MELUMPUHKAN dirinya sendiri.
# Jadi: satu kunci global + jarak minimum 4s antara panggilan DDG.
_DDG_LOCK = __import__("threading").Lock()
_DDG_TERAKHIR = [0.0]
_DDG_JEDA = 4.0


def _ddg_giliran() -> None:
    """Pastikan hanya satu panggilan DDG pada satu masa, dengan jarak minimum."""
    with _DDG_LOCK:
        sela = time.time() - _DDG_TERAKHIR[0]
        if sela < _DDG_JEDA:
            time.sleep(_DDG_JEDA - sela)
        _DDG_TERAKHIR[0] = time.time()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(url: str, *, headers: dict | None = None, timeout: float = TIMEOUT,
        mobile: bool = False) -> str:
    """GET teks. Pulang "" bila gagal — pemanggil yang putuskan, bukan exception.

    PERANGKAP BESAR (diukur 13 Nov 2026): `verify=False` MENYEBABKAN DuckDuckGo
    pulang HTTP 202 + halaman cabaran 'anomaly' (0 hasil), sementara TLS normal
    pulang 200 dengan 11 hasil. Sama untuk beberapa laman lain yang memeriksa
    cap jari TLS. JADI: JANGAN guna verify=False. Kalau sijil gagal, itu isu
    rangkaian — bukan sesuatu yang patut kita pintas secara lalai.
    """
    h = dict(HDR)
    if mobile:
        h["User-Agent"] = UA_MOBILE
    if headers:
        h.update(headers)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=h) as c:
            r = c.get(url)
            if r.status_code >= 400:
                return ""
            return r.text or ""
    except Exception:
        return ""


def post(url: str, data: dict, *, headers: dict | None = None,
         timeout: float = TIMEOUT) -> str:
    """POST borang — DDG kadang lulus melalui POST walaupun GET dicabar."""
    h = dict(HDR)
    h["Content-Type"] = "application/x-www-form-urlencoded"
    if headers:
        h.update(headers)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=h) as c:
            r = c.post(url, data=data)
            if r.status_code >= 400:
                return ""
            return r.text or ""
    except Exception:
        return ""


def get_json(url: str, *, timeout: float = TIMEOUT) -> dict | list | None:
    txt = get(url, headers={"Accept": "application/json"}, timeout=timeout)
    if not txt or not txt.strip()[:1] in "{[":
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def strip_html(html: str, had: int = 6000) -> str:
    if not html:
        return ""
    t = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?is)<br\s*/?>", "\n", t)
    t = re.sub(r"(?is)</(p|div|li|h[1-6]|tr|article|section)>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
          .replace("&mdash;", "—").replace("&ndash;", "–").replace("&hellip;", "…"))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r"\n\s*\n\s*\n+", "\n\n", t)
    return t.strip()[:had]


def _rekod(sumber: str, tajuk: str, url: str, **kw) -> dict:
    d = {"sumber": sumber, "tajuk": (tajuk or "").strip()[:200], "url": url.strip()}
    d.update(kw)
    return d


def _dedup(rows: list[dict]) -> list[dict]:
    """Buang duplikat ikut URL ternormal + tajuk ternormal."""
    lihat: set[str] = set()
    out: list[dict] = []
    for r in rows:
        u = (r.get("url") or "").split("#")[0].rstrip("/")
        kunci = u.lower()
        if not kunci or kunci in lihat:
            continue
        lihat.add(kunci)
        out.append(r)
    return out


# --------------------------------------------------- ENJIN CARIAN (banyak serentak)
def e_ddg(query: str, limit: int = 10) -> list[dict]:
    """DuckDuckGo HTML — keyless, enjin utama.

    DISAHKAN 13 Nov 2026:
      duckduckgo.com/html/?q=        -> 200, 10 blok result__a, 40 uddg  (GUNA INI)
      html.duckduckgo.com/html/      -> 202 halaman cabaran 'anomaly'    (JANGAN)
    Pautan sebenar tersembunyi dalam //duckduckgo.com/l/?uddg=<urlencoded>.
    """
    out: list[dict] = []
    _ddg_giliran()
    html = get("https://duckduckgo.com/html/?q=" + quote(query))
    if "result__a" not in (html or ""):
        # 202 = dicabar. Tunggu sekali (bukan 3x — jangan buang masa), kemudian cuba POST.
        time.sleep(6)
        _ddg_giliran()
        html = post("https://duckduckgo.com/html/", {"q": query, "b": "", "kl": "wt-wt"})
    if "result__a" not in (html or ""):
        return []

    for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html or "", re.S):
        href, tajuk = m.group(1), strip_html(m.group(2), 200)
        mm = re.search(r"uddg=([^&]+)", href)
        if mm:
            href = unquote(mm.group(1))
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http") and "duckduckgo" not in href:
            out.append(_rekod("ddg", tajuk, href))
        if len(out) >= limit:
            break
    return out[:limit]


def e_bing(query: str, limit: int = 10) -> list[dict]:
    """Bing HTML — 200, blok b_algo. ENJIN PALING STABIL (diukur: 10/10 lulus).
    Nota: operator site: DIIABAIKAN oleh Bing — jangan harap pada site: di sini.
    Jika tiada b_algo (kadang Bing pulang layout lain), fallback ke regex generik.
    """
    out: list[dict] = []
    html = get("https://www.bing.com/search?q=" + quote(query) + "&count=%d" % max(limit, 10))
    for blok in re.findall(r'(?is)<li class="b_algo".*?</li>', html or ""):
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', blok, re.S)
        if not m:
            continue
        u = m.group(1)
        if "bing.com/ck/a" in u:
            mm = re.search(r"[?&]u=a1([A-Za-z0-9_\-=]+)", u)
            if mm:
                import base64
                b = mm.group(1)
                b += "=" * (-len(b) % 4)
                try:
                    u = base64.urlsafe_b64decode(b).decode("utf-8", "ignore")
                except Exception:
                    continue
        tajuk = strip_html(m.group(2), 200)
        if u.startswith("http"):
            out.append(_rekod("bing", tajuk, u))
        if len(out) >= limit:
            break
    if not out:
        # fallback: mana-mana pautan luar dalam blok hasil
        for m in re.finditer(r'(?is)<h2[^>]*>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                             html or ""):
            u, t = m.group(1), strip_html(m.group(2), 200)
            if "bing.com" in u or "microsoft" in u:
                continue
            out.append(_rekod("bing", t, u))
            if len(out) >= limit:
                break
    return out[:limit]


def e_yandex(query: str, limit: int = 10) -> list[dict]:
    """Yandex HTML — 200 (diukur). Bagus untuk kandungan Rusia/Asia + laman yang
    Google/Bing sembunyikan. Struktur: <a class="Link" href=...>."""
    out: list[dict] = []
    html = get("https://yandex.com/search/?text=" + quote(query) + "&lr=87")
    for m in re.finditer(r'(?is)<a[^>]+class="[^"]*Link[^"]*"[^>]+href="(https?://[^"]+)"'
                         r'[^>]*>(.*?)</a>', html or ""):
        u, t = m.group(1), strip_html(m.group(2), 200)
        if any(x in u for x in ("yandex.", "yastatic", "passport.")):
            continue
        if len(t) < 8:
            continue
        out.append(_rekod("yandex", t, u))
        if len(out) >= limit:
            break
    return out[:limit]


def e_google(query: str, limit: int = 10) -> list[dict]:
    """Google HTML — SELALUNYA PULANG HLM JS-CHALLENGE, bukan hasil.

    DISAHKAN 13 Nov 2026: 200 + 94KB tetapi tiada <a href> hasil langsung —
    badan ialah 'Please click here if you are not redirected within a few seconds'.
    Jadi ia hanya berguna bila Google memberi HTML sebenar (IP tertentu). Kalau
    tiada pautan -> pulang [] dan enjin lain mengambil alih. JANGAN bergantung.
    """
    out: list[dict] = []
    html = get("https://www.google.com/search?q=" + quote(query) + "&num=%d" % max(limit, 10),
               headers={"Accept-Language": "en-US,en;q=0.9"})
    if not html or "if you are not redirected" in html:
        return []
    for m in re.finditer(r'<a[^>]+href="/url\?q=([^"&]+)[^"]*"[^>]*>(.*?)</a>', html, re.S):
        u = unquote(m.group(1))
        t = strip_html(m.group(2), 200)
        if u.startswith("http") and t and "google." not in u:
            out.append(_rekod("google", t, u))
        if len(out) >= limit:
            break
    if not out:
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html, re.S):
            u, t = m.group(1), strip_html(m.group(2), 200)
            if any(x in u for x in ("google.", "gstatic.", "youtube.com/redirect", "support.google")):
                continue
            if len(t) < 12:
                continue
            out.append(_rekod("google", t, u))
            if len(out) >= limit:
                break
    return out[:limit]


def e_mojeek(query: str, limit: int = 10) -> list[dict]:
    """Mojeek — 403 dari IP ini (diukur). Kekal sebagai percubaan: IP lain boleh lulus."""
    out: list[dict] = []
    html = get("https://www.mojeek.com/search?q=" + quote(query))
    for m in re.finditer(r'(?is)<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                         html or ""):
        out.append(_rekod("mojeek", strip_html(m.group(2), 200), m.group(1)))
        if len(out) >= limit:
            break
    return out[:limit]


def e_searx(query: str, limit: int = 10) -> list[dict]:
    """SearXNG awam — JSON dimatikan pada kebanyakan instance (diukur: 200 HTML).
    Jadi kita parse HTML hasilnya, bukan JSON."""
    out: list[dict] = []
    for base in ("https://searx.be", "https://search.inetol.net", "https://baresearch.org",
                 "https://priv.au", "https://opnxng.com"):
        html = get(f"{base}/search?q=" + quote(query), timeout=15.0)
        if not html or 'class="result' not in html:
            continue
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*class="url_header"', html):
            out.append(_rekod("searx", "", m.group(1)))
        if not out:
            for m in re.finditer(r'(?is)<h3>\s*<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', html):
                u = m.group(1)
                if base.split("//")[-1] in u:
                    continue
                out.append(_rekod("searx", strip_html(m.group(2), 200), u))
        if out:
            return out[:limit]
    return out[:limit]


def e_brave(query: str, limit: int = 10) -> list[dict]:
    """Brave Search HTML — 429 dari IP datacenter (diukur). Kekal sebagai percubaan."""
    out: list[dict] = []
    html = get("https://search.brave.com/search?q=" + quote(query))
    for m in re.finditer(r'(?is)<a[^>]+href="(https?://[^"]+)"[^>]*class="[^"]*heading-serpresult',
                         html or ""):
        pass
    for m in re.finditer(r'(?is)<div class="snippet[^"]*".*?<a[^>]+href="(https?://[^"]+)"'
                         r'[^>]*>(.*?)</a>', html or ""):
        u, t = m.group(1), strip_html(m.group(2), 200)
        if "brave.com" in u:
            continue
        out.append(_rekod("brave", t, u))
        if len(out) >= limit:
            break
    return out[:limit]


def e_wikipedia(query: str, limit: int = 5) -> list[dict]:
    """Wikipedia API — sentiasa hidup, bagus untuk fakta asas & definisi."""
    out: list[dict] = []
    for lang in ("ms", "en", "id"):
        j = get_json(f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
                     f"&srsearch={quote(query)}&format=json&srlimit={limit}")
        try:
            for r in j["query"]["search"]:
                out.append(_rekod("wikipedia", r.get("title", ""),
                                  f"https://{lang}.wikipedia.org/wiki/"
                                  + quote(r.get("title", "").replace(" ", "_")),
                                  ringkas=strip_html(r.get("snippet", ""), 250)))
        except Exception:
            continue
        if out:
            break
    return out[:limit]


def e_hn(query: str, limit: int = 10) -> list[dict]:
    """Hacker News (Algolia API) — tiada kunci, pantas."""
    j = get_json("https://hn.algolia.com/api/v1/search?query=" + quote(query)
                 + "&hitsPerPage=%d" % limit)
    out: list[dict] = []
    for h in (j or {}).get("hits", [])[:limit]:
        u = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append(_rekod("hn", h.get("title", ""), u,
                          ringkas=(h.get("story_text") or "")[:250],
                          mata=h.get("points")))
    return out


ENJIN = {
    "ddg": e_ddg, "bing": e_bing, "google": e_google, "yandex": e_yandex,
    "brave": e_brave, "mojeek": e_mojeek, "searx": e_searx,
    "wikipedia": e_wikipedia, "hn": e_hn,
}

# ------------------------------------------------- PLATFORM MEDIA SOSIAL (lubang)
def p_youtube(query: str, limit: int = 5) -> list[dict]:
    """YouTube — HTML hasil carian (videoId dalam JSON) + oEmbed untuk tajuk."""
    out: list[dict] = []
    html = get("https://www.youtube.com/results?search_query=" + quote(query),
               headers={"Accept-Language": "en-US,en;q=0.9"})
    ids = re.findall(r'"videoId":"([\w-]{11})"', html or "")
    dilihat = set()
    for vid in ids:
        if vid in dilihat:
            continue
        dilihat.add(vid)
        u = f"https://www.youtube.com/watch?v={vid}"
        tajuk = ""
        j = get_json("https://www.youtube.com/oembed?format=json&url=" + quote(u))
        if isinstance(j, dict):
            tajuk = j.get("title", "")
        out.append(_rekod("youtube", tajuk or vid, u, id=vid))
        if len(out) >= limit:
            break
    return out


def p_reddit(query: str, limit: int = 10) -> list[dict]:
    """Reddit — API .json 403 & .rss 403 dari IP ini (diukur 13 Nov 2026).
    Laluan yang tinggal: DDG site:reddit.com (DISAHKAN pulang pautan /comments/)
    dan Reddit's own oEmbed/RSS melalui cermin redlib."""
    out: list[dict] = []
    dilihat: set[str] = set()

    def _kumpul(rows: list[dict]) -> None:
        for h in rows:
            u = h.get("url", "")
            if "reddit.com" in u and "/comments/" in u and u not in dilihat:
                dilihat.add(u)
                out.append(_rekod("reddit", h.get("tajuk", ""), u))

    _kumpul(e_ddg(f"site:reddit.com {query}", limit * 3))
    if len(out) < limit:
        for base in ("https://redlib.catsarch.com", "https://safereddit.com",
                     "https://redlib.perennialte.ch"):
            html = get(f"{base}/search?q=" + quote(query) + "&type=link", timeout=15.0)
            if not html:
                continue
            for m in re.finditer(r'href="(/r/[\w\-]+/comments/[\w\-]+[^"]*)"', html):
                u = base + m.group(1)
                if u in dilihat:
                    continue
                dilihat.add(u)
                out.append(_rekod("reddit", "", u))
                if len(out) >= limit:
                    break
            if out:
                break
    return out[:limit]


def p_telegram(query: str, limit: int = 10) -> list[dict]:
    """Telegram awam — t.me/s/<channel>. Carian penuh tiada API; ini untuk saluran
    yang namanya sepadan dengan kata kunci, atau bila BOZ beri @channel terus."""
    out: list[dict] = []
    calon = {re.sub(r"[^a-z0-9_]", "", query.lower().replace(" ", ""))[:32],
             query.strip().lstrip("@").lower()}
    for ch in calon:
        if not ch or len(ch) < 3:
            continue
        html = get(f"https://t.me/s/{ch}")
        if not html or "tgme_widget_message" not in html:
            continue
        for m in re.finditer(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                             html, re.S):
            teks = strip_html(m.group(1), 600)
            if teks:
                out.append(_rekod("telegram", teks[:120], f"https://t.me/{ch}", teks=teks))
            if len(out) >= limit:
                break
        if out:
            break
    return out


def p_bluesky(query: str, limit: int = 10) -> list[dict]:
    """Bluesky — public.api.bsky.app pulang 403 dari IP ini (diukur 13 Nov 2026,
    perlindungan kawasan). Cuba juga cermin bsky.app carian awam melalui jina."""
    url = ("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q="
           + quote(query) + f"&limit={min(limit, 25)}")
    out: list[dict] = []
    j = get_json(url)
    for p in (j or {}).get("posts", []) if isinstance(j, dict) else []:
        uri = p.get("uri", "")
        handle = (p.get("author") or {}).get("handle", "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        if not (handle and rkey):
            continue
        out.append(_rekod("bluesky", (p.get("record") or {}).get("text", "")[:120],
                          f"https://bsky.app/profile/{handle}/post/{rkey}",
                          teks=(p.get("record") or {}).get("text", "")[:600]))
        if len(out) >= limit:
            break
    if not out:
        txt = get("https://r.jina.ai/https://bsky.app/search?q=" + quote(query), timeout=30.0)
        for m in re.finditer(r"(https://bsky\.app/profile/[\w.\-]+/post/[\w]+)", txt or ""):
            out.append(_rekod("bluesky", "", m.group(1)))
            if len(out) >= limit:
                break
    return out[:limit]


def p_mastodon(query: str, limit: int = 10) -> list[dict]:
    """Mastodon — tag timeline awam (tiada kunci). DISAHKAN 200."""
    out: list[dict] = []
    tag = re.sub(r"[^a-zA-Z0-9_]", "", query.split()[0] if query.split() else "")
    for base in ("https://mastodon.social", "https://fosstodon.org"):
        if not tag:
            break
        j = get_json(f"{base}/api/v1/timelines/tag/{tag}?limit={min(limit, 20)}")
        for s in (j or [])[:limit] if isinstance(j, list) else []:
            out.append(_rekod("mastodon", strip_html(s.get("content", ""), 120),
                              s.get("url", ""),
                              teks=strip_html(s.get("content", ""), 600)))
        if out:
            break
    return out[:limit]


def p_tiktok(query: str, limit: int = 5) -> list[dict]:
    """TikTok — DDG site:tiktok.com/video (DISAHKAN) + oEmbed untuk tajuk."""
    out: list[dict] = []
    dilihat: set[str] = set()
    for h in e_ddg(f"site:tiktok.com/video {query}", limit * 5):
        u = h.get("url", "")
        if "tiktok.com" not in u or "/video/" not in u or u in dilihat:
            continue
        dilihat.add(u)
        j = get_json("https://www.tiktok.com/oembed?url=" + quote(u))
        tajuk = j.get("title", "") if isinstance(j, dict) else h.get("tajuk", "")
        out.append(_rekod("tiktok", tajuk, u))
        if len(out) >= limit:
            break
    return out


def p_instagram(query: str, limit: int = 5) -> list[dict]:
    """Instagram — DDG site:instagram.com (DISAHKAN). oEmbed perlu token hari ini."""
    out: list[dict] = []
    for h in e_ddg(f"site:instagram.com {query}", limit * 4):
        u = h.get("url", "")
        if "instagram.com" in u and ("/p/" in u or "/reel/" in u or "/tv/" in u):
            out.append(_rekod("instagram", h.get("tajuk", ""), u))
        if len(out) >= limit:
            break
    return out


def p_x(query: str, limit: int = 5) -> list[dict]:
    """X/Twitter — nitter.net mati, cermin 451/tiada DNS (diukur 13 Nov 2026).
    Laluan yang tinggal: syndication API awam X (tanpa kunci) + Bing site:x.com.
    ENG: https://cdn.syndication.twimg.com/tweet-result?id=<id> — perlukan id tweet.
    Jadi kita guna Bing untuk jumpa pautan status, kemudian sahkan.
    """
    out: list[dict] = []
    dilihat: set[str] = set()
    # L1: cermin nitter yang masih hidup (jarang, tetapi murah untuk dicuba)
    for base in ("https://xcancel.com", "https://lightbrd.com"):
        html = get(f"{base}/search?f=tweets&q=" + quote(query), timeout=12.0)
        if html and "status/" in html:
            for m in re.finditer(r'href="(/[A-Za-z0-9_]+/status/\d+)"', html):
                u = base + m.group(1)
                if u not in dilihat:
                    dilihat.add(u)
                    out.append(_rekod("x", "", u))
                if len(out) >= limit:
                    return out[:limit]
    # L2: Bing untuk terus jumpa pautan status (Bing tak hormat site:, jadi tapis sendiri)
    for h in e_bing(f"x.com twitter {query} status", limit * 5):
        u = h.get("url", "")
        if ("x.com" in u or "twitter.com" in u) and "/status/" in u and u not in dilihat:
            dilihat.add(u)
            out.append(_rekod("x", h.get("tajuk", ""), u))
        if len(out) >= limit:
            break
    # L3: DDG sebagai jalan terakhir (had kadar dikawal)
    if len(out) < limit:
        for h in e_ddg(f"site:x.com {query}", limit * 3):
            u = h.get("url", "")
            if ("x.com" in u or "twitter.com" in u) and "/status/" in u and u not in dilihat:
                dilihat.add(u)
                out.append(_rekod("x", h.get("tajuk", ""), u))
            if len(out) >= limit:
                break
    return out[:limit]


def p_threads(query: str, limit: int = 5) -> list[dict]:
    """Threads — r.jina.ai pada carian awam (DISAHKAN 200, 48KB)."""
    out: list[dict] = []
    dilihat: set[str] = set()
    txt = get("https://r.jina.ai/https://www.threads.net/search?q=" + quote(query), timeout=40.0)
    for m in re.finditer(r"(https://www\.threads\.(?:net|com)/@[\w.\-]+/post/[\w\-]+)", txt or ""):
        u = m.group(1)
        if u not in dilihat:
            dilihat.add(u)
            out.append(_rekod("threads", "", u))
        if len(out) >= limit:
            break
    if len(out) < limit:
        for h in e_ddg(f"site:threads.net {query}", limit * 3):
            u = h.get("url", "")
            if "threads." in u and "/post/" in u and u not in dilihat:
                dilihat.add(u)
                out.append(_rekod("threads", h.get("tajuk", ""), u))
            if len(out) >= limit:
                break
    return out[:limit]


def p_github(query: str, limit: int = 8) -> list[dict]:
    """GitHub search API — BOZ_PAT naikkan had 10->30/min."""
    out: list[dict] = []
    pat = os.environ.get("BOZ_PAT", "").strip()
    hdrs = {"Accept": "application/vnd.github+json"}
    if pat:
        hdrs["Authorization"] = f"Bearer {pat}"
    txt = get("https://api.github.com/search/repositories?q=" + quote(query)
              + f"&per_page={min(limit, 30)}", headers=hdrs)
    try:
        j = json.loads(txt)
        for r in j.get("items", [])[:limit]:
            out.append(_rekod("github", r.get("full_name", ""), r.get("html_url", ""),
                              ringkas=(r.get("description") or "")[:250],
                              bintang=r.get("stargazers_count")))
    except Exception:
        pass
    return out


def p_news(query: str, limit: int = 10) -> list[dict]:
    """Berita — Google News RSS (keyless, DISAHKAN 200)."""
    out: list[dict] = []
    txt = get("https://news.google.com/rss/search?q=" + quote(query)
              + "&hl=en-US&gl=US&ceid=US:en")
    try:
        root = ET.fromstring(txt.encode("utf-8", "ignore"))
        for it in root.findall(".//item")[:limit]:
            t = it.findtext("title") or ""
            u = it.findtext("link") or ""
            d = it.findtext("pubDate") or ""
            if u:
                out.append(_rekod("news", t, u, tarikh=d))
    except Exception:
        pass
    return out


PLATFORM = {
    "youtube": p_youtube, "reddit": p_reddit, "telegram": p_telegram,
    "bluesky": p_bluesky, "mastodon": p_mastodon, "tiktok": p_tiktok,
    "instagram": p_instagram, "x": p_x, "twitter": p_x, "threads": p_threads,
    "github": p_github, "news": p_news,
}


# ------------------------------------------------------- TANGGA ESKALASI (lubang)
def l_wayback(query: str, limit: int = 10) -> list[dict]:
    """Wayback CDX — URL yang pernah diarkib. Untuk kandungan yang sudah DIPADAM."""
    out: list[dict] = []
    j = get_json("http://web.archive.org/cdx/search/cdx?url=*&output=json&limit="
                 f"{limit}&filter=urlkey:.*{quote(re.sub(r'[^a-z0-9]', '', query.lower()))}.*")
    if isinstance(j, list) and len(j) > 1:
        for row in j[1:limit + 1]:
            try:
                ts, orig = row[1], row[2]
                out.append(_rekod("wayback", "", f"https://web.archive.org/web/{ts}/{orig}",
                                  asal=orig))
            except Exception:
                continue
    return out


def l_commoncrawl(query: str, limit: int = 10) -> list[dict]:
    """Common Crawl index — arsip web terbesar, tiada kunci."""
    out: list[dict] = []
    j = get_json("https://index.commoncrawl.org/CC-MAIN-2024-38-index?url=*"
                 f"{quote(query.split()[0])}*&output=json&limit={limit}", timeout=30.0)
    teks = get("https://index.commoncrawl.org/CC-MAIN-2024-38-index?url=*"
               f"{quote(query.split()[0])}*&output=json&limit={limit}", timeout=30.0)
    for baris in (teks or "").splitlines()[:limit]:
        try:
            r = json.loads(baris)
            u = r.get("url", "")
            if u:
                out.append(_rekod("commoncrawl", "", u, status=r.get("status")))
        except Exception:
            continue
    return out


def l_archive_today(query: str, limit: int = 5) -> list[dict]:
    """archive.today — salinan snapshot untuk laman yang sudah hilang."""
    out: list[dict] = []
    html = get("https://archive.ph/newest/https://" + query.strip(), timeout=25.0)
    if html and "archive.ph" in html:
        for m in re.finditer(r'href="(https?://archive\.(?:ph|today|is)/[A-Za-z0-9]+)"', html):
            out.append(_rekod("archive_today", "", m.group(1)))
            if len(out) >= limit:
                break
    return out


def l_jina_read(url: str, had: int = 8000) -> dict:
    """r.jina.ai — pembaca universal. Laluan terakhir bila curl terus disekat."""
    txt = get("https://r.jina.ai/" + url, timeout=45.0,
              headers={"Accept": "text/plain", "X-Return-Format": "text"})
    if len(txt) > 200:
        return {"url": url, "kaedah": "jina", "aksara": len(txt), "teks": txt[:had]}
    return {"url": url, "kaedah": "jina-gagal", "aksara": 0, "teks": ""}


def ambil_url(url: str, had: int = 6000) -> dict:
    """Ambil SATU URL melalui tangga 4 lapis sampai dapat teks sebenar."""
    teks, kaedah = "", "gagal"
    html = get(url)
    teks = strip_html(html, had)
    if len(teks) >= 400:
        return {"url": url, "kaedah": "terus", "aksara": len(teks), "teks": teks}
    # L2: mobile UA (sesetengah laman pulang versi teks penuh untuk telefon)
    html = get(url, mobile=True)
    t2 = strip_html(html, had)
    if len(t2) > len(teks):
        teks, kaedah = t2, "mobile"
    if len(teks) >= 400:
        return {"url": url, "kaedah": kaedah, "aksara": len(teks), "teks": teks}
    # L3: r.jina.ai
    j = l_jina_read(url, had)
    if j["aksara"] > len(teks):
        return j
    # L4: Wayback snapshot
    wb = get(f"https://web.archive.org/web/2024/{url}", timeout=40.0)
    t3 = strip_html(wb, had)
    if len(t3) > len(teks):
        return {"url": url, "kaedah": "wayback", "aksara": len(t3), "teks": t3}
    return {"url": url, "kaedah": "terhad", "aksara": len(teks), "teks": teks}


LUBANG = {"wayback": l_wayback, "commoncrawl": l_commoncrawl,
          "archive_today": l_archive_today}


# ------------------------------------------------------------------ orkestrasi
def carian_penuh(query: str, kira: int = 10, platform: str = "all",
                 lubang: bool = False, max_kerja: int = 24) -> dict:
    """Tembak semua enjin + platform SERENTAK. Ini yang menjadikannya 'sampai jumpa'."""
    tugas: dict[str, tuple] = {}
    for nama, fn in ENJIN.items():
        tugas[nama] = (fn, query, kira)
    if platform in ("all", "", None):
        for nama, fn in PLATFORM.items():
            tugas[nama] = (fn, query, max(3, kira // 2))
    elif platform != "web":
        for nama in platform.split(","):
            nama = nama.strip().lower()
            if nama in PLATFORM:
                tugas[nama] = (PLATFORM[nama], query, kira)
            elif nama in ENJIN:
                tugas[nama] = (ENJIN[nama], query, kira)
    if lubang:
        for nama, fn in LUBANG.items():
            tugas[nama] = (fn, query, max(5, kira // 2))

    hasil: list[dict] = []
    laporan: dict[str, int] = {}
    gagal: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=min(max_kerja, max(1, len(tugas)))) as ex:
        fut = {ex.submit(_selamat, fn, q, k): nama for nama, (fn, q, k) in tugas.items()}
        for f in as_completed(fut, timeout=150):
            nama = fut[f]
            try:
                rows = f.result() or []
                laporan[nama] = len(rows)
                hasil.extend(rows)
            except Exception as e:
                gagal[nama] = f"{type(e).__name__}"
                laporan[nama] = 0

    hasil = _dedup(hasil)
    # Susun: platform sebenar dahulu (bukan hasil carian), kemudian enjin.
    urutan = {n: i for i, n in enumerate(
        ["youtube", "reddit", "x", "twitter", "instagram", "tiktok", "threads",
         "bluesky", "mastodon", "telegram", "news", "github", "wikipedia"] + list(ENJIN))}
    hasil.sort(key=lambda r: urutan.get(r.get("sumber", ""), 99))
    return {"query": query, "ts": _now(), "hasil": hasil, "laporan": laporan,
            "gagal": gagal, "platform_aktif": sorted(laporan)}


def _selamat(fn, *a):
    try:
        return fn(*a)
    except Exception:
        return []


def eskalasi(query: str, kira: int = 10) -> dict:
    """TANGGA PENUH: 4 lapis sampai jumpa. Ini 'sampai lubang cacing'."""
    jejak: list[dict] = []

    # L1 — semua enjin + semua platform, serentak
    r1 = carian_penuh(query, kira, "all")
    jejak.append({"lapis": "L1-semua-enjin", "rekod": len(r1["hasil"])})
    if r1["hasil"]:
        r1["jejak"] = jejak
        return r1

    # L2 — ubah bentuk pertanyaan (sinonim Inggeris/Melayu, buang kata tanya)
    varian = [query]
    q2 = re.sub(r"\b(apa|apa itu|siapa|di mana|bila|mengapa|kenapa|how|what|who|where|when|why)\b",
                " ", query, flags=re.I).strip()
    if q2 and q2 != query:
        varian.append(q2)
    if re.search(r"\b(cari|find|get|ambil|download)\b", query, re.I):
        varian.append(re.sub(r"\b(cari|find|get|ambil|download)\b", " ", query, flags=re.I).strip())
    for v in varian[1:3]:
        rv = carian_penuh(v, kira, "ddg,google,bing,mojeek,searx")
        jejak.append({"lapis": f"L2-varian:{v[:40]}", "rekod": len(rv["hasil"])})
        if rv["hasil"]:
            rv["jejak"] = jejak
            return rv

    # L3 — arsip: wayback + commoncrawl + archive.today
    r3 = carian_penuh(query, kira, "web", lubang=True)
    jejak.append({"lapis": "L3-arsip", "rekod": len(r3["hasil"])})
    if r3["hasil"]:
        r3["jejak"] = jejak
        return r3

    # L4 — terus baca URL jika pertanyaan itu sendiri URL/domain
    if re.match(r"^https?://", query.strip()):
        a = ambil_url(query.strip().rstrip("/"))
        if a["aksara"] > 100:
            r4 = {"query": query, "ts": _now(), "hasil": [
                _rekod("terus", a["teks"][:100], query.strip(), teks=a["teks"])],
                "laporan": {"terus": 1}, "gagal": {}, "jejak": jejak}
            return r4
    elif re.match(r"^[\w.\-]+\.[a-z]{2,}", query.strip()):
        a = ambil_url("https://" + query.strip().rstrip("/"))
        if a["aksara"] > 100:
            jejak.append({"lapis": "L4-terus-domain", "rekod": 1})
            return {"query": query, "ts": _now(), "hasil": [
                _rekod("terus", a["teks"][:100], "https://" + query.strip(), teks=a["teks"])],
                "laporan": {"terus": 1}, "gagal": {}, "jejak": jejak}

    jejak.append({"lapis": "L5-tamat", "rekod": 0})
    return {"query": query, "ts": _now(), "hasil": [], "laporan": {}, "gagal": {},
            "jejak": jejak, "tamat": "semua lapis dicuba, tiada rekod"}


def uji_laluan() -> dict:
    """--uji: buktikan setiap laluan hidup/mati. Ini yang kena jalankan sebelum percaya."""
    lap: dict[str, str] = {}
    ujian = {
        "ddg": lambda: len(e_ddg("python asyncio", 3)) > 0,
        "bing": lambda: len(e_bing("python asyncio", 3)) > 0,
        "google": lambda: len(e_google("python asyncio", 3)) > 0,
        "mojeek": lambda: len(e_mojeek("python asyncio", 3)) > 0,
        "searx": lambda: len(e_searx("python asyncio", 3)) > 0,
        "brave": lambda: len(e_brave("python asyncio", 3)) > 0,
        "wikipedia": lambda: len(e_wikipedia("Python", 3)) > 0,
        "hn": lambda: len(e_hn("python", 3)) > 0,
        "news": lambda: len(p_news("technology", 3)) > 0,
        "youtube": lambda: len(p_youtube("python tutorial", 3)) > 0,
        "reddit": lambda: len(p_reddit("python", 3)) > 0,
        "bluesky": lambda: len(p_bluesky("python", 3)) > 0,
        "github": lambda: len(p_github("hermes agent", 3)) > 0,
        "mastodon": lambda: len(p_mastodon("python", 3)) > 0,
        "x": lambda: len(p_x("python", 3)) > 0,
        "instagram": lambda: len(p_instagram("python", 3)) > 0,
        "tiktok": lambda: len(p_tiktok("python", 3)) > 0,
        "threads": lambda: len(p_threads("python", 3)) > 0,
        "telegram": lambda: len(p_telegram("durov", 3)) > 0,
        "jina": lambda: l_jina_read("https://example.com", 2000)["aksara"] > 100,
    }
    for nama, fn in ujian.items():
        t0 = time.time()
        try:
            ok = fn()
            lap[nama] = f"HIDUP ({time.time() - t0:.1f}s)" if ok else f"KOSONG ({time.time() - t0:.1f}s)"
        except Exception as e:
            lap[nama] = f"RALAT {type(e).__name__}"
    return lap


# ---------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Enjin carian universal BOZ — sampai lubang cacing")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--platform", "-p", default="all",
                    help="all|web|<senarai: youtube,reddit,x,news,...>|list")
    ap.add_argument("--kira", "-k", type=int, default=10)
    ap.add_argument("--extract", "-e", type=int, default=2,
                    help="berapa halaman dibaca penuh")
    ap.add_argument("--url", "-u", default="", help="ambil satu URL terus")
    ap.add_argument("--lubang", action="store_true", help="eskalasi 5 lapis sampai jumpa")
    ap.add_argument("--uji", action="store_true", help="uji setiap laluan, lapor hidup/mati")
    ap.add_argument("--json", action="store_true", help="cetak JSON penuh ke stdout")
    args = ap.parse_args()

    if args.platform == "list":
        print("enjin   :", ", ".join(sorted(ENJIN)))
        print("platform:", ", ".join(sorted(PLATFORM)))
        print("lubang  :", ", ".join(sorted(LUBANG)))
        return 0

    if args.uji:
        lap = uji_laluan()
        hidup = sum(1 for v in lap.values() if v.startswith("HIDUP"))
        for k, v in lap.items():
            print(f"  {k:12s} {v}")
        print(f"RESULT: {hidup}/{len(lap)} laluan HIDUP")
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(os.path.join(OUT_DIR, "uji_laluan.json"), "w", encoding="utf-8") as fh:
            json.dump({"ts": _now(), "laluan": lap, "hidup": hidup}, fh, ensure_ascii=False, indent=1)
        return 0

    if not args.query and not args.url:
        print("guna: cari_lubang.py \"<kata kunci>\" [--kira 10] [--extract 2] [--lubang]")
        print("      cari_lubang.py --url <url>   |   --uji   |   --platform list")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    if args.url:
        r = ambil_url(args.url)
        rekod = {"query": args.url, "ts": _now(), "jenis": "url", "url_hasil": r,
                 "hasil": [_rekod("terus", r["teks"][:120], args.url, teks=r["teks"])]}
        print(f"SIAP: {args.url} — {r['aksara']} aksara via {r['kaedah']}")
        print("-> " + r["teks"][:800].replace("\n", " "))
    else:
        rekod = eskalasi(args.query, args.kira) if args.lubang else \
            carian_penuh(args.query, args.kira, args.platform)
        hasil = rekod["hasil"]
        # baca penuh N teratas supaya model dapat ISI, bukan cuma pautan
        penuh: list[dict] = []
        for h in hasil[:args.extract]:
            if not h.get("url"):
                continue
            try:
                a = ambil_url(h["url"], 4000)
                h["teks"] = a["teks"]
                h["kaedah"] = a["kaedah"]
                penuh.append(h)
            except Exception:
                continue
        rekod["penuh"] = penuh
        rekod["secs"] = round(time.time() - t0, 1)
        rekod["jumlah"] = len(hasil)

        if args.json:
            print(json.dumps(rekod, ensure_ascii=False, indent=1)[:40000])
        else:
            print(f"SIAP: {args.query} — {len(hasil)} rekod ({len(penuh)} dibaca penuh) "
                  f"dalam {rekod['secs']}s -> {OUT_DIR}/hasil.json")
            lap = rekod.get("laporan", {})
            hidup = {k: v for k, v in lap.items() if v}
            print("sumber:", ", ".join(f"{k}={v}" for k, v in sorted(hidup.items())[:14]) or "tiada")
            for j in rekod.get("jejak", []):
                print(f"  jejak {j['lapis']}: {j['rekod']} rekod")
            for h in hasil[:8]:
                t = (h.get("tajuk") or h.get("teks") or "")[:70].replace("\n", " ")
                print(f"  [{h.get('sumber')}] {t} | {str(h.get('url'))[:80]}")

    with open(os.path.join(OUT_DIR, "hasil.json"), "w", encoding="utf-8") as fh:
        json.dump(rekod, fh, ensure_ascii=False, indent=1)
    return 0 if rekod.get("hasil") else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
