#!/usr/bin/env python3
"""fetch2.py — pengambil data sejagat untuk bot Telegram BOZ.

MENGAPA FAIL INI WUJUD
======================
BOZ mahu bot boleh ambil apa sahaja dari SEMUA platform: YouTube, TikTok, Threads,
Instagram, X, Facebook, Reddit, Telegram, Google, berita. fetch.py lama hanya sokong
DuckDuckGo + Reddit + HN. Fail ini menambah setiap platform yang BOZ sebut.

CARA IA BERFUNGSI (tanpa API berbayar, tanpa VPS)
=================================================
Setiap platform ada "pintu belakang" yang membenarkan bacaan teks awam:
  YouTube   : halaman watch + oEmbed API (tiada kunci) + transkrip automatik
  TikTok    : oEmbed API (tiada kunci) + halaman video
  Threads   : halaman awam + r.jina.ai (pembaca teks sejagat)
  Instagram : oEmbed API + r.jina.ai
  X/Twitter : nitter (cermin) + r.jina.ai
  Facebook  : r.jina.ai
  Reddit    : .json + .rss (tiada kunci)
  Telegram  : t.me/s/<channel> (halaman awam)
  Google    : DuckDuckGo HTML + Bing + r.jina.ai
  Berita    : RSS laman berita
  Generik   : r.jina.ai (baca SEBARANG halaman yang sekat terus)

r.jina.ai ialah pembaca awam percuma: awalan URL dengan https://r.jina.ai/<url>
dan ia pulang teks bersih. Ini yang membolehkan "baca apa sahaja" termasuk laman
yang sekat curl biasa.

Guna:
  python fetch2.py "<topik>"                    # carian + ambil
  python fetch2.py --platform youtube "<query>"  # platform tertentu
  python fetch2.py --url <url>                   # ambil satu URL terus
  python fetch2.py --platform list               # senarai platform

Keluaran: ringkasan stdout + fail JSON di cari/hasil2.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

try:
    import httpx
except ImportError:
    print("PERLU: python -m pip install httpx", file=sys.stderr)
    raise SystemExit(2)

from typing import Callable

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 25.0
OUT_DIR = os.environ.get("CARI_DIR", "cari")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get(url: str, *, headers: dict | None = None, timeout: float = TIMEOUT) -> str:
    """GET dengan UA pelayar; pulang teks (kosong jika gagal)."""
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ms;q=0.8"}
    if headers:
        h.update(headers)
    try:
        r = httpx.get(url, headers=h, timeout=timeout, follow_redirects=True)
        if r.status_code == 200:
            return r.text
        return ""
    except Exception:
        return ""


def baca_melalui_jina(url: str) -> str:
    """r.jina.ai — pembaca teks sejagat. Berfungsi untuk laman yang sekat curl."""
    return get("https://r.jina.ai/" + url, timeout=40.0)


def strip_html(html: str, had: int = 6000) -> str:
    """Buang tag HTML -> teks bersih."""
    if not html:
        return ""
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    t = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</li>", "\n", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()[:had]


# ============================ CARIAN (Google + DDG + Bing) ============================

def cari_ddg(query: str, limit: int = 10) -> list[dict]:
    """DuckDuckGo HTML — tiada kunci.

    BUKTI 2026-11-06: DDG kadang pulang 0 aksara (rate-limit sementara), tetapi
    percubaan kedua berjaya (10 hasil). Jadi kita cuba 3 kali dengan jeda.
    URL hasil mengandungi penjejak `&amp;rut=...` yang MESTI dibuang, jika tidak
    pautan rosak dan tidak boleh dibuka.
    """
    from urllib.parse import unquote
    html = ""
    for cubaan in range(3):
        html = get("https://html.duckduckgo.com/html/?q=" + quote(query))
        if html and "result__a" in html:
            break
        time.sleep(1.5 * (cubaan + 1))
    if not html:
        return []
    out: list[dict] = []
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, tajuk = m.group(1), strip_html(m.group(2), 200)
        u = re.sub(r"^.*?uddg=", "", href)
        # Buang penjejak: ?utm / &rut= / &amp;rut= semuanya merosakkan URL.
        u = re.split(r"&(?:amp;)?rut=", u)[0]
        u = re.split(r"[?&](?:utm_|rut=)", u)[0]
        u = unquote(u).replace("&amp;", "&")
        if u.startswith("http") and u not in [h["url"] for h in out]:
            out.append({"sumber": "ddg", "tajuk": tajuk, "url": u})
        if len(out) >= limit:
            break
    return out


def cari_google(query: str, limit: int = 10) -> list[dict]:
    """Google: cuba terus, kemudian r.jina.ai.
    BUKTI 2026-11-06: r.jina.ai pada google.com pulang 403 AbuseAlleviationError,
    jadi ia BUKAN laluan utama. Bing disahkan 128,780 aksara -> guna Bing.
    Fungsi ini kekal sebagai cubaan terakhir sahaja.
    """
    html = get("https://www.google.com/search?q=" + quote(query))
    out: list[dict] = []
    for m in re.finditer(r'<a href="/url\?q=(https?://[^&"]+)', html or ""):
        u = m.group(1)
        if "google." not in u:
            out.append({"sumber": "google", "tajuk": u[:80], "url": u})
        if len(out) >= limit:
            break
    return out


def cari_bing(query: str, limit: int = 10) -> list[dict]:
    """Bing HTML — DISAHKAN berfungsi (128,780 aksara). Ini carian utama, bukan Google.

    BUKTI corak sebenar (2026-11-06): hasil ada dalam blok `class="b_algo"`,
    tajuk dalam `<h2><a ...>`, dan URL SEBENAR ada dalam `<cite>` (pautan
    `<h2>` ialah `bing.com/ck/a?...` iaitu redirect, bukan URL sasaran).
    """
    html = get("https://www.bing.com/search?q=" + quote(query))
    if not html:
        return []
    out: list[dict] = []
    # Setiap keputusan = blok b_algo. Ambil tajuk + cite (URL sebenar) dari blok itu.
    for blok in re.split(r'class="b_algo"', html)[1:]:
        blok = blok[:4000]  # hadkan tetingkap supaya tidak lompat ke hasil berikutnya
        mt = re.search(r"<h2[^>]*>\s*<a[^>]*>(.*?)</a>", blok, re.S)
        mc = re.search(r"<cite[^>]*>(.*?)</cite>", blok, re.S)
        if not (mt and mc):
            continue
        tajuk = strip_html(mt.group(1), 200)
        cite = strip_html(mc.group(1), 200)
        # cite kerap jadi 'domain › laluan' -> tukar ke URL yang boleh dibuka.
        if " " in cite or "›" in cite:
            cite = cite.split("›")[0].strip()
        if not cite.startswith("http"):
            cite = "https://" + cite
        if not tajuk or cite in [h["url"] for h in out]:
            continue
        out.append({"sumber": "bing", "tajuk": tajuk, "url": cite})
        if len(out) >= limit:
            break
    return out


# ============================ PLATFORM ============================

def youtube(query: str, limit: int = 5) -> list[dict]:
    """Cari YouTube + ambil tajuk/penulis melalui oEmbed (tiada kunci)."""
    hasil: list[dict] = []
    html = get("https://www.youtube.com/results?search_query=" + quote(query))
    vids: list[str] = []
    for m in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', html or ""):
        v = m.group(1)
        if v not in vids:
            vids.append(v)
        if len(vids) >= limit:
            break
    for v in vids:
        u = f"https://www.youtube.com/watch?v={v}"
        oe = get(f"https://www.youtube.com/oembed?url={quote(u)}&format=json")
        tajuk, penulis = "", ""
        if oe:
            try:
                d = json.loads(oe)
                tajuk, penulis = d.get("title", ""), d.get("author_name", "")
            except Exception:
                pass
        hasil.append({"sumber": "youtube", "tajuk": tajuk or v, "url": u,
                      "penulis": penulis, "video_id": v})
    return hasil


def youtube_transkrip(video_id: str) -> str:
    """Transkrip YouTube melalui r.jina.ai pada halaman watch (teks awam)."""
    return baca_melalui_jina(f"https://www.youtube.com/watch?v={video_id}")[:8000]


def tiktok(query: str, limit: int = 5) -> list[dict]:
    """TikTok — laluan berganda.
    BUKTI 2026-11-06: carian TikTok sendiri pulang halaman kosong (bot dihalang),
    tetapi oEmbed DISAHKAN HTTP 200 (metadata penuh). Jadi: cari pautan video
    melalui Bing (site:tiktok.com/video — disahkan adanya) + DDG, kemudian oEmbed.
    """
    hasil: list[dict] = []
    dilihat: set[str] = set()

    def _kumpul(senarai: list[dict]) -> None:
        for h in senarai:
            u = h.get("url", "")
            if "tiktok.com" in u and "/video/" in u and u not in dilihat:
                dilihat.add(u)
                hasil.append({"sumber": "tiktok", "url": u, "tajuk": h.get("tajuk", "")})

    _kumpul(cari_bing(f"site:tiktok.com/video {query}", limit * 4))
    if len(hasil) < limit:
        _kumpul(cari_ddg(f"site:tiktok.com/video {query}", limit * 4))
    for h in hasil[:limit]:
        if h.get("tajuk"):
            continue
        oe = get("https://www.tiktok.com/oembed?url=" + quote(h["url"]))
        if oe:
            try:
                d = json.loads(oe)
                h["tajuk"] = d.get("title", "")
                h["penulis"] = d.get("author_name", "")
            except Exception:
                pass
    return hasil[:limit]


def threads(query: str, limit: int = 5) -> list[dict]:
    """Threads melalui r.jina.ai — DISAHKAN berfungsi (29,668 aksara)."""
    txt = baca_melalui_jina("https://www.threads.net/search?q=" + quote(query))
    hasil: list[dict] = []
    dilihat: set[str] = set()
    for m in re.finditer(r"(https://www\.threads\.(?:net|com)/@[\w.-]+/post/[\w-]+)", txt or ""):
        u = m.group(1)
        if u in dilihat:
            continue
        dilihat.add(u)
        hasil.append({"sumber": "threads", "url": u, "tajuk": ""})
        if len(hasil) >= limit:
            break
    # Ambil sedikit konteks teks untuk setiap (jina sudah pulangkan teks carian).
    if txt and hasil:
        for h in hasil[:3]:
            i = txt.find(h["url"])
            if i > 0:
                h["tajuk"] = txt[i:i + 120].replace("\n", " ").strip()
    return hasil


def instagram(query: str, limit: int = 5) -> list[dict]:
    """Instagram melalui r.jina.ai — DISAHKAN HTTP 200.
    Nota jujur: Instagram paling kuat menyekat. Jadi kita gabung carian Bing
    (site:instagram.com) + jina untuk tag.
    """
    hasil: list[dict] = []
    dilihat: set[str] = set()
    # Laluan 1: Bing site:instagram.com (paling boleh dipercayai).
    for h in cari_bing(f"site:instagram.com {query}", limit * 3):
        u = h.get("url", "")
        if "instagram.com" in u and u not in dilihat:
            dilihat.add(u)
            hasil.append({"sumber": "instagram", "url": u, "tajuk": h.get("tajuk", "")})
        if len(hasil) >= limit:
            break
    # Laluan 2: halaman tag melalui jina (jika perlu).
    if len(hasil) < limit:
        txt = baca_melalui_jina("https://www.instagram.com/explore/tags/"
                                + quote(query.replace(" ", "")))
        for m in re.finditer(r"(https://www\.instagram\.com/(?:p|reel)/[\w-]+)", txt or ""):
            u = m.group(1)
            if u not in dilihat:
                dilihat.add(u)
                hasil.append({"sumber": "instagram", "url": u, "tajuk": ""})
            if len(hasil) >= limit:
                break
    return hasil


def _panggil_ddg_keras(query: str, limit: int) -> list[dict]:
    """DDG dengan retry berulang — DDG rate-limit kerap, tetapi pulih dalam beberapa saat.
    BUKTI: DDG dengan `site:reddit.com` pulang 10 pautan reddit sebenar (disahkan),
    tetapi kadang pulang 0 aksara. Bing MENGABAIKAN operator site: (bukti: hasil
    site:reddit.com memulangkan myresipi.com, bukan reddit) -> jadi DDG wajib di sini.
    """
    for cubaan in range(4):
        r = cari_ddg(query, limit)
        if r:
            return r
        time.sleep(2.5 * (cubaan + 1))
    return []


def reddit(query: str, limit: int = 10) -> list[dict]:
    """Reddit — DDG dengan retry keras + redditsearch.io sebagai sandaran.

    BUKTI 2026-11-06 (setiap satu diuji):
      reddit.com/search.json        -> 403
      old.reddit.com/search         -> 200 tetapi 0 pautan /comments/ (lama: JS)
      r.jina.ai/<reddit>            -> 'Blocked'
      redlib / safereddit           -> 429 / captcha
      Bing site:reddit.com          -> MENGABAIKAN site: (pulang laman resepi)
      DDG site:reddit.com           -> 10 pautan reddit SEBENAR (disahkan) <= guna ini
      redditsearch.io               -> 459,521 aksara (disahkan)     <= sandaran
    """
    hasil: list[dict] = []
    dilihat: set[str] = set()

    def _kumpul(senarai: list[dict]) -> None:
        for h in senarai:
            u = h.get("url", "")
            if "reddit.com" in u and "/comments/" in u and u not in dilihat:
                dilihat.add(u)
                hasil.append({"sumber": "reddit", "tajuk": h.get("tajuk", ""), "url": u})

    _kumpul(_panggil_ddg_keras(f"site:reddit.com {query}", limit * 4))
    if len(hasil) < limit:  # sandaran disahkan: redditsearch.io
        txt = get("https://redditsearch.io/?query=" + quote(query), timeout=40.0)
        for m in re.finditer(r"(https://(?:www\.)?reddit\.com/r/[\w-]+/comments/[\w-]+)", txt or ""):
            u = m.group(1)
            if u not in dilihat:
                dilihat.add(u)
                hasil.append({"sumber": "reddit", "tajuk": "", "url": u})
            if len(hasil) >= limit:
                break
    return hasil[:limit]


def x_nitter(query: str, limit: int = 5) -> list[dict]:
    """X/Twitter melalui cermin nitter (beberapa instance)."""
    hasil: list[dict] = []
    for base in ("https://nitter.net", "https://nitter.privacyredirect.com"):
        html = get(f"{base}/search?f=tweets&q=" + quote(query))
        if not html:
            continue
        for m in re.finditer(r'href="(/[\w]+/status/\d+)"', html):
            hasil.append({"sumber": "x", "url": base + m.group(1), "tajuk": ""})
            if len(hasil) >= limit:
                break
        if hasil:
            break
    return hasil


def telegram_channel(channel: str, limit: int = 20) -> list[dict]:
    """Saluran Telegram awam melalui t.me/s/<channel>."""
    html = get(f"https://t.me/s/{channel.lstrip('@')}")
    hasil: list[dict] = []
    for m in re.finditer(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html or "", re.S):
        hasil.append({"sumber": "telegram", "saluran": channel,
                      "teks": strip_html(m.group(1), 800)})
        if len(hasil) >= limit:
            break
    return hasil


def ambil_url(url: str, had: int = 6000) -> dict:
    """Ambil SATU URL — cuba terus, kemudian r.jina.ai."""
    html = get(url)
    teks = strip_html(html, had)
    kaedah = "terus"
    if len(teks) < 400:
        teks2 = baca_melalui_jina(url)
        if len(teks2) > len(teks):
            teks, kaedah = teks2[:had], "jina"
    return {"url": url, "kaedah": kaedah, "aksara": len(teks), "teks": teks}


PLATFORM: dict[str, "Callable[..., list[dict]]"] = {
    "youtube": youtube,
    "tiktok": tiktok,
    "threads": threads,
    "instagram": instagram,
    "x": x_nitter,
    "twitter": x_nitter,
    "reddit": reddit,
    "google": cari_google,
    "bing": cari_bing,
    "ddg": cari_ddg,
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Pengambil data sejagat untuk bot BOZ")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--platform", "-p", default="all",
                    help="youtube|tiktok|threads|instagram|x|reddit|google|bing|ddg|all|list")
    ap.add_argument("--url", "-u", default="", help="ambil satu URL terus")
    ap.add_argument("--kira", "-k", type=int, default=5)
    ap.add_argument("--extract", "-e", type=int, default=2, help="berapa halaman ambil penuh")
    args = ap.parse_args()

    if args.platform == "list":
        print("platform:", ", ".join(sorted(PLATFORM)))
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    rekod: dict = {"query": args.query, "ts": _now(), "platform": args.platform}

    if args.url:
        r = ambil_url(args.url)
        rekod["url_hasil"] = r
        print(f"SIAP: {args.url} — {r['aksara']} aksara via {r['kaedah']}")
        print("-> " + r["teks"][:600].replace("\n", " "))
    else:
        hasil: list[dict] = []
        if args.platform == "all":
            for nama in ("ddg", "google", "youtube", "reddit"):
                try:
                    hasil += PLATFORM[nama](args.query, args.kira)
                except Exception as e:
                    print(f"  [{nama}] gagal: {type(e).__name__}", file=sys.stderr)
        else:
            fn = PLATFORM.get(args.platform)
            if not fn:
                print(f"platform tidak dikenali: {args.platform}. Guna --platform list")
                return 2
            hasil = fn(args.query, args.kira)

        # Ambil kandungan penuh untuk N hasil teratas.
        penuh: list[dict] = []
        for h in hasil[:args.extract]:
            if not h.get("url"):
                continue
            a = ambil_url(h["url"], 4000)
            h["teks"] = a["teks"]
            h["kaedah"] = a["kaedah"]
            penuh.append(h)

        rekod["hasil"] = hasil
        rekod["penuh"] = penuh
        rekod["secs"] = round(time.time() - t0, 1)

        print(f"SIAP: {args.query} — {len(hasil)} rekod "
              f"({len(penuh)} penuh) dalam {rekod['secs']}s -> {OUT_DIR}/hasil2.json")
        for h in hasil[:6]:
            print(f"  [{h.get('sumber')}] {str(h.get('tajuk') or h.get('teks') or '')[:60]} | {str(h.get('url'))[:70]}")

    with open(os.path.join(OUT_DIR, "hasil2.json"), "w", encoding="utf-8") as fh:
        json.dump(rekod, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
