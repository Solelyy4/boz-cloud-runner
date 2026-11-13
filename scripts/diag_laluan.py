#!/usr/bin/env python3
"""diag_laluan.py — ukur SETIAP laluan carian: status HTTP + panjang + punca.

Bukan tekaan: cetak kod status, mime, panjang badan, dan petikan 200 aksara supaya
kita tahu SAMA ADA disekat, layout berubah, atau parser kita salah.
"""
import sys
import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
H = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
     "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"}

SASARAN = [
    ("ddg-html", "https://html.duckduckgo.com/html/?q=python+asyncio"),
    ("ddg-lite", "https://lite.duckduckgo.com/lite/?q=python+asyncio"),
    ("google", "https://www.google.com/search?q=python+asyncio&num=10"),
    ("mojeek", "https://www.mojeek.com/search?q=python+asyncio"),
    ("brave", "https://search.brave.com/search?q=python+asyncio"),
    ("searx.be", "https://searx.be/search?q=python+asyncio&format=json"),
    ("reddit-rss", "https://www.reddit.com/search.rss?q=python&sort=relevance"),
    ("reddit-rss2", "https://www.reddit.com/search/.rss?q=python"),
    ("bluesky", "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=python&limit=5"),
    ("xcancel", "https://xcancel.com/search?f=tweets&q=python"),
    ("nitter-poast", "https://nitter.poast.org/search?f=tweets&q=python"),
    ("instagram-ddg", "https://html.duckduckgo.com/html/?q=site%3Ainstagram.com+python"),
    ("tiktok-ddg", "https://html.duckduckgo.com/html/?q=site%3Atiktok.com%2Fvideo+python"),
    ("threads-jina", "https://r.jina.ai/https://www.threads.net/search?q=python"),
    ("startpage", "https://www.startpage.com/sp/search?query=python+asyncio"),
    ("marginalia", "https://search.marginalia.nu/search?query=python+asyncio"),
    ("yandex", "https://yandex.com/search/?text=python+asyncio"),
    ("ecosia", "https://www.ecosia.org/search?q=python+asyncio"),
    ("presearch", "https://presearch.com/search?q=python+asyncio"),
]

for nama, url in SASARAN:
    try:
        with httpx.Client(follow_redirects=True, timeout=18.0, headers=H, verify=False) as c:
            r = c.get(url)
        body = r.text or ""
        ctype = r.headers.get("content-type", "")[:40]
        print(f"{nama:16s} {r.status_code} {len(body):7d}B {ctype:40s} {body[:110].replace(chr(10),' ')!r}")
    except Exception as e:
        print(f"{nama:16s} RALAT {type(e).__name__}: {str(e)[:90]}")
