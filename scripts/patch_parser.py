#!/usr/bin/env python3
"""patch_parser.py — ganti blok parser dalam cari_lubang.py dengan versi DISAHKAN.

Setiap regex di sini diuji terhadap HTML SEBENAR (bukan andaian). Bila layout laman
berubah, jalankan scripts/diag_laluan.py dulu dan kemas kini di sini — jangan teka.
"""
import io
import re
import sys

PATH = "scripts/cari_lubang.py"
src = io.open(PATH, encoding="utf-8").read()

# ---------------------------------------------------------------- enjin blok baru
ENJIN_BARU = r'''# --------------------------------------------------- ENJIN CARIAN (banyak serentak)
def e_ddg(query: str, limit: int = 10) -> list[dict]:
    """DuckDuckGo HTML — keyless, enjin utama.

    DISAHKAN 13 Nov 2026:
      duckduckgo.com/html/?q=        -> 200, 10 blok result__a, 40 uddg  (GUNA INI)
      html.duckduckgo.com/html/      -> 202 halaman cabaran 'anomaly'    (JANGAN)
    Pautan sebenar tersembunyi dalam //duckduckgo.com/l/?uddg=<urlencoded>.
    """
    out: list[dict] = []
    html = get("https://duckduckgo.com/html/?q=" + quote(query))
    if "result__a" not in (html or ""):
        html = post("https://duckduckgo.com/html/", {"q": query, "b": "", "kl": "wt-wt"})
    if "result__a" not in (html or ""):
        html = post("https://lite.duckduckgo.com/lite/", {"q": query})

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
    """Bing HTML — 200, blok b_algo. Nota: operator site: DIIABAIKAN oleh Bing."""
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
    "ddg": e_ddg, "bing": e_bing, "google": e_google, "brave": e_brave,
    "mojeek": e_mojeek, "searx": e_searx, "wikipedia": e_wikipedia, "hn": e_hn,
}
'''

# ------------------------------------------------- platform blok baru (disahkan)
PLATFORM_BARU = r'''# ------------------------------------------------- PLATFORM MEDIA SOSIAL (lubang)
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
    """X/Twitter — nitter.net mati; cermin lain 451; DDG site:x.com (DISAHKAN)."""
    out: list[dict] = []
    dilihat: set[str] = set()
    for base in ("https://xcancel.com", "https://lightbrd.com",
                 "https://nitter.privacyredirect.com"):
        html = get(f"{base}/search?f=tweets&q=" + quote(query), timeout=15.0)
        if not html or "status/" not in html:
            continue
        for m in re.finditer(r'href="(/[A-Za-z0-9_]+/status/\d+)"', html):
            u = base + m.group(1)
            if u not in dilihat:
                dilihat.add(u)
                out.append(_rekod("x", "", u))
            if len(out) >= limit:
                break
        if out:
            return out
    for h in e_ddg(f"site:x.com OR site:twitter.com {query}", limit * 4):
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
'''

# --- potong & ganti blok enjin ---
m1 = re.search(r"# -{2,} ENJIN CARIAN.*?\n(?=\n# -{2,} PLATFORM MEDIA SOSIAL|\n\nPLATFORM = \{)", src, re.S)
if not m1:
    print("GAGAL: blok ENJIN tidak dijumpai")
    sys.exit(1)
src = src[:m1.start()] + ENJIN_BARU + src[m1.end():]

# --- potong & ganti blok platform ---
m2 = re.search(r"PLATFORM = \{.*?\n\}\n", src, re.S)
if not m2:
    print("GAGAL: blok PLATFORM tidak dijumpai")
    sys.exit(2)
# cari permulaan blok platform (komen header) hingga PLATFORM dict tamat
start = src.rfind("# -{2,} PLATFORM MEDIA SOSIAL", 0, m2.start())
if start == -1:
    start = src.rfind("#", 0, m2.start())
src = src[:start] + PLATFORM_BARU + src[m2.end():]

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print(f"OK: {PATH} ditulis semula ({len(src)} bait)")
print("  ENJIN   :", len(re.findall(r"^def e_", src, re.M)), "fungsi")
print("  PLATFORM:", len(re.findall(r"^def p_", src, re.M)), "fungsi")
print("  verify=False:", src.count("verify=False"), "(mesti 0)")
