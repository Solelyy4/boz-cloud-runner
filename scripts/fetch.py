#!/usr/bin/env python3
"""
BOZ CARI-LUAR — pemacu deterministik untuk bot Telegram.

Kenapa skrip ini ada: model kecil (8b/14b) TIDAK boleh dipercayai merancang
gelung berbilang langkah (cari -> buka 5 pautan -> parse -> simpan fail).
Ia berhenti selepas 1-2 langkah atau mencipta gelung. Skrip ini buat kerja
itu secara DETERMINISTIK: satu arahan masuk, fail keluar + ringkasan.

Guna dari Telegram (bot panggil melalui alat terminal):
    python scripts/fetch.py "harga bitcoin hari ini" --kira 8
    python scripts/fetch.py "python asyncio tutorial" --extract 5
    python scripts/fetch.py --reddit python --limit 50
    python scripts/fetch.py "berita AI" --json out.json

Hasil: fail dalam <cwd>/cari/ + ringkasan ditulis ke stdout (bot baca ini).
Tiada data direka. Kalau sumber gagal, laporkan ralat mentah + pivot.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 25
WIB = timezone(timedelta(hours=7))


def _now() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")


def get(url: str, *, headers: dict | None = None, data: bytes | None = None,
        timeout: int = TIMEOUT) -> tuple[int, bytes]:
    """HTTP GET/POST mentah. Pulangkan (status, body). 0 = ralat rangkaian."""
    h = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ms;q=0.8"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, data=data,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, (e.read() or b"")[:2000]
    except Exception as e:  # noqa: BLE001 — ralat rangkaian pelbagai jenis
        return 0, str(e).encode()


def search_ddg(query: str, limit: int = 10) -> list[dict]:
    """Carian DuckDuckGo HTML (keyless). Tangga bila kosong."""
    out: list[dict] = []
    q = urllib.parse.quote_plus(query)
    for url in (f"https://html.duckduckgo.com/html/?q={q}",
                f"https://lite.duckduckgo.com/lite/?q={q}"):
        code, body = get(url)
        if code != 200:
            continue
        html = body.decode("utf-8", "replace")
        # hasil DDG HTML: <a class="result__a" href="...">tajuk</a>
        for m in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html, re.S | re.I):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            href = _clean_ddg_url(href)
            if href.startswith("http"):
                out.append({"title": _unesc(title).strip(), "url": href,
                            "snippet": ""})
            if len(out) >= limit:
                break
        if out:
            break
        # fallback: lite layout <a rel="nofollow" href=...>
        for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                             html, re.S | re.I):
            href, title = m.group(1), _unesc(re.sub(r"<[^>]+>", "", m.group(2)))
            if "duckduckgo" in href or not title.strip():
                continue
            out.append({"title": title.strip(), "url": href, "snippet": ""})
            if len(out) >= limit:
                break
        if out:
            break
    return out[:limit]


def _clean_ddg_url(href: str) -> str:
    """DDG bungkus pautan dalam /l/?uddg=<encoded>."""
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return urllib.parse.unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def _unesc(s: str) -> str:
    import html as _h
    return _h.unescape(s)


def extract(url: str, char_limit: int = 4000) -> dict:
    """Ambil kandungan satu halaman. Tangga: asal -> jina.ai -> archive."""
    steps = [
        ("direct", url),
        ("r.jina.ai", "https://r.jina.ai/" + url),
        ("archive", "https://web.archive.org/save/" + url),
    ]
    last_code = 0
    for name, target in steps:
        code, body = get(target, timeout=40)
        last_code = code
        if code == 200 and body:
            text = body.decode("utf-8", "replace")
            if name == "direct":
                text = _strip_html(text)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
            if len(text) > 120:
                return {"url": url, "via": name, "chars": len(text),
                        "text": text[:char_limit]}
    return {"url": url, "via": "gagal", "chars": 0,
            "text": f"[TERHALANG] HTTP {last_code} untuk {url}"}


def _strip_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|h[1-6]|li|tr)>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return _unesc(html)


def reddit(sub: str, sort: str = "hot", limit: int = 50) -> list[dict]:
    """Reddit — .rss jalan (JSON API 403/429 sejak Reddit blok UA skrip).

    Tangga: .rss (200) -> .json -> redlib. Parsing tanpa xml lib (regex ringkas).
    """
    headers = {"Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8"}
    for path in (f"/r/{sub}/{sort}/.rss", f"/r/{sub}/{sort}.rss"):
        url = "https://www.reddit.com" + path
        code, body = get(url, headers=headers)
        if code != 200 or len(body) < 500:
            continue
        xml = body.decode("utf-8", "replace")
        out: list[dict] = []
        for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
            blk = m.group(1)
            t = re.search(r"<title>(.*?)</title>", blk, re.S)
            l = re.search(r'<link[^>]+href="([^"]+)"', blk)
            a = re.search(r"<name>(.*?)</name>", blk, re.S)
            u = re.search(r"<updated>(.*?)</updated>", blk, re.S)
            out.append({
                "title": _unesc((t.group(1) if t else "").strip()),
                "url": (l.group(1) if l else ""),
                "author": (a.group(1) if a else ""),
                "updated": (u.group(1) if u else ""),
            })
            if len(out) >= limit:
                break
        if out:
            return out
    # Tangga akhir: JSON API (mungkin lolos dari IP lain)
    code, body = get(f"https://www.reddit.com/r/{sub}/{sort}.json?limit={limit}",
                     headers={"Accept": "application/json"})
    if code == 200:
        try:
            d = json.loads(body)
            return [{"title": (p.get("data") or {}).get("title", ""),
                     "url": "https://reddit.com" + (p.get("data") or {}).get("permalink", ""),
                     "score": (p.get("data") or {}).get("score", 0)}
                    for p in (d.get("data") or {}).get("children") or []][:limit]
        except Exception:  # noqa: BLE001
            pass
    return []


def hackernews(query: str = "", limit: int = 30) -> list[dict]:
    """Hacker News Algolia API — stabil, keyless."""
    if query:
        url = ("https://hn.algolia.com/api/v1/search?query="
               + urllib.parse.quote_plus(query) + f"&hitsPerPage={limit}")
    else:
        url = f"https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}"
    code, body = get(url)
    if code != 200:
        return []
    try:
        d = json.loads(body)
    except Exception:  # noqa: BLE001
        return []
    return [{"title": h.get("title") or h.get("story_title") or "",
             "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
             "points": h.get("points") or 0, "comments": h.get("num_comments") or 0}
            for h in (d.get("hits") or [])][:limit]


def main() -> int:
    ap = argparse.ArgumentParser(description="BOZ cari-luar deterministik")
    ap.add_argument("query", nargs="?", default="", help="kata kunci carian")
    ap.add_argument("--kira", type=int, default=10, help="bilangan hasil carian")
    ap.add_argument("--extract", type=int, default=0,
                    help="ambil kandungan N pautan teratas")
    ap.add_argument("--reddit", default="", help="subreddit (tanpa r/)")
    ap.add_argument("--hn", action="store_true", help="cari Hacker News")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--json", default="", help="tulis hasil penuh ke fail ini")
    ap.add_argument("--outdir", default="cari")
    args = ap.parse_args()

    if not args.query and not args.reddit and not args.hn:
        ap.error("perlu query, --reddit SUB, atau --hn")

    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)
    hasil: dict = {"masa": _now(), "query": args.query, "sumber": {}}

    # 1) Carian web
    if args.query:
        hits = search_ddg(args.query, args.kira)
        hasil["sumber"]["ddg"] = hits
        if not hits:
            hits = hackernews(args.query, args.kira)
            hasil["sumber"]["hn_fallback"] = hits

    # 2) Reddit
    if args.reddit:
        hasil["sumber"]["reddit"] = reddit(args.reddit, limit=args.limit)

    # 3) HN
    if args.hn:
        hasil["sumber"]["hn"] = hackernews(args.query, args.limit)

    # 4) Ambil kandungan N pautan teratas
    if args.extract and args.query:
        top = (hasil["sumber"].get("ddg") or hasil["sumber"].get("hn_fallback")
               or hasil["sumber"].get("hn") or [])[: args.extract]
        docs = []
        for h in top:
            d = extract(h["url"])
            d["title"] = h.get("title", "")
            docs.append(d)
            print(f"  ambil {d['via']:<10} {d['chars']:>6} aksara  {h['url'][:70]}",
                  file=sys.stderr)
            time.sleep(0.7)
        hasil["dokumen"] = docs

    # Tulis fail penuh
    jpath = Path(args.json) if args.json else (outdir / "hasil.json")
    jpath.write_text(json.dumps(hasil, ensure_ascii=False, indent=1),
                     encoding="utf-8")

    # Ringkasan untuk bot (padat — bot baca stdout ini)
    total = sum(len(v) for v in hasil["sumber"].values() if isinstance(v, list))
    print(f"SIAP: {args.query or args.reddit or 'hn'} — {total} rekod -> {jpath}")
    for nama, senarai in hasil["sumber"].items():
        if isinstance(senarai, list):
            for h in senarai[:3]:
                t = (h.get("title") or "")[:60]
                print(f"-> [{nama}] {t} | {h.get('url','')[:70]}")
    if hasil.get("dokumen"):
        ok = sum(1 for d in hasil["dokumen"] if d["chars"] > 0)
        print(f"-> kandungan: {ok}/{len(hasil['dokumen'])} halaman diambil")
    return 0


if __name__ == "__main__":
    sys.exit(main())
