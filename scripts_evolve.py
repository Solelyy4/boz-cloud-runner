#!/usr/bin/env python3
"""scripts_evolve.py — ENJIN AUTO-EVOLUSI BOT BOZ (menggantikan autolearn + selfupgrade).

Setiap pusingan (tiap 10 minit):
 1. AUDIT  — kira skill, config, SOUL/AGENTS, saiz prompt; tulis AUDIT.md + state/evolve.json
 2. BELAJAR— pilih domain yang paling kurang liputan (bukan giliran buta), riset DDG + Wikipedia,
             tulis/perkaya skills/<domain>/SKILL.md dengan nota pendek yang berguna.
 3. DIALEK— kandung domain ke dalam pengunci bahasa autolearn (en/bm/id/zh/ar/ru/fr/es) supaya
             permintaan BOZ dalam mana-mana bahasa dipetakan ke domain skill yang betul.
 4. KUAT   — tulis kurang < 300 bait dianggap GAGAL → domain kekal dalam senarai.

Deterministik, tiada API berbayar, tiada agent agentic yang boleh habis iterasi.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from base64 import urlsafe_b64decode
from html import unescape as html_unescape

HOME = pathlib.Path(os.environ["HERMES_HOME"])
SKILLS = HOME / "skills"
STATE = HOME / "state"
LOG = STATE / "evolve.jsonl"
MIN_BYTES = 300

# (domain, petunjuk, kata kunci dialek) — kata kunci ditulis dalam skrip asal supaya
# domain kelihatan walaupun permintaan BOZ bukan dalam bahasa Inggeris.
DOMAINS: list[tuple[str, str, list[str]]] = [
    ("web-exploit-advanced", "SQLi/SSRF/deserialization/XSS, bypass WAF; sqlmap, ffuf, nuclei, curl_cffi",
     ["sql injection", "ssrf", "xss", "waf", "injection sql", "suntikan sql", "跨站", "инъекция"]),
    ("smart-contract-deep", "reentrancy, oracle manipulation, flash loan, ERC quirks; foundry, cast, anvil fork",
     ["reentrancy", "flash loan", "oracle", "erc20", "دrain", "kontrak pintar", "智能合约", "смарт-контракт"]),
    ("osint-full-stack", "Sherlock, Maigret, Wayback, crt.sh, RDAP, DNS history, satelit, EXIF",
     ["osint", "sherlock", "wayback", "whois", "jejak", "سجل", "情报", "разведка"]),
    ("malware-evasion-modern", "loader, AMSI bypass, ETW patch, process injection, C2 profile",
     ["malware", "loader", "amsi", "rat", "evasion", "برمجية", "恶意软件", "вредонос"]),
    ("cloud-privesc-aws-gcp-azure", "IAM enumeration, metadata SSRF, role chain, bucket abuse",
     ["aws", "azure", "gcp", "iam", "bucket", "metadata", "سحابة", "云", "облако"]),
    ("mobile-android-ios", "Frida, objection, apktool, jailbreak, SSL pinning bypass",
     ["android", "ios", "frida", "apk", "jailbreak", "أندرويد", "安卓", "андроид"]),
    ("api-graphql-abuse", "BOLA, introspection, batching, rate limit bypass, mass assignment",
     ["graphql", "bola", "idor", "api", "rate limit", "واجهة", "接口", "api"]),
    ("container-k8s-escape", "privileged pod, hostPath, service account token, cgroup escape",
     ["kubernetes", "docker", "k8s", "pod", "escape", "حاوية", "容器", "контейнер"]),
    ("network-protocol-attacks", "ARP spoof, DHCP, DNS rebinding, TLS downgrade, BGP",
     ["arp", "dhcp", "dns", "bgp", "sniff", "شبكة", "网络", "сеть"]),
    ("windows-ad-attack-paths", "Kerberoast, AS-REP, DCSync, ADCS ESC1-8, BloodHound",
     ["kerberos", "activedirectory", "dcsync", "bloodhound", "ad", "دومين", "域", "домен"]),
    ("linux-privesc-modern", "SUID, capabilities, cron, NFS, PwnKit, polkit, kernel",
     ["suid", "sudo", "kernel", "privesc", "permission", "صلاحيات", "提权", "права"]),
    ("reverse-engineering-binary", "Ghidra, IDA, angr, symbolic exec, unpacking",
     ["ghidra", "ida", "disassembly", "reverse", "angr", "هندسة", "逆向", "реверс"]),
    ("bug-bounty-methodology", "recon pipeline, scope mapping, IDOR 2-account proof, report",
     ["bug bounty", "hackerone", "bugcrowd", "report", "memburu", "ثغرة", "漏洞", "баг"]),
    ("ai-prompt-injection", "indirect injection, tool abuse, guardrail bypass, exfil via tools",
     ["prompt injection", "jailbreak", "llm", "guardrail", "حقن", "注入", "инъекция"]),
    ("supply-chain-attack", "typosquat, dependency confusion, CI poisoning, npm/pypi",
     ["npm", "pypi", "dependency", "supply chain", "typosquat", "سلسلة", "供应链", "цепочка"]),
    ("browser-extension-abuse", "permission abuse, content script, native messaging, MV3",
     ["extension", "chrome", "manifest", "browser", "sambungan", "ضافة", "扩展", "расширение"]),
    ("crypto-onchain-forensics", "tx tracing, mixer, cluster address, Dune, Etherscan API",
     ["wallet", "ethereum", "tracing", "mixer", "blockchain", "محفظة", "区块链", "блокчейн"]),
    ("social-engineering-modern", "pretexting, AiTM, MFA fatigue, vishing, deepfake voice",
     ["phishing", "pretexting", "vishing", "aitm", "mfa", "تصيد", "钓鱼", "фишинг"]),
    ("data-engineering-pipelines", "ETL, dbt, Airflow, warehouse, kafka; scheduling & retry",
     ["etl", "airflow", "dbt", "kafka", "pipeline", "بيانات", "数据", "данные"]),
    ("devops-cicd-abuse", "pipeline secrets, runner takeover, artifact poisoning, OIDC abuse",
     ["cicd", "github actions", "jenkins", "runner", "secret", "خط أنابيب", "流水线", "конвейер"]),
]

DIALEK = ["en", "bm", "id", "zh", "ar", "ru", "fr", "es", "th", "vi", "hi", "tr"]


def fetch(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) boz-evolve/1.0",
            "Accept-Language": "en-US,en;q=0.9,ms;q=0.8,zh;q=0.7",
        },
    )
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def riset_ddg(domain: str) -> list[str]:
    """DuckDuckGo HTML — sering disekat (202 bot-wall). Kekal sebagai pilihan pertama."""
    out: list[str] = []
    q = urllib.parse.quote(domain.replace("-", " ") + " techniques tools 2026")
    for endpoint in ("https://html.duckduckgo.com/html/?q={q}",
                     "https://lite.duckduckgo.com/lite/?q={q}"):
        try:
            html = fetch(endpoint.format(q=q))
            for href, title in re.findall(r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)[:8]:
                t = re.sub(r"<[^>]+>", "", title).strip()
                if not t:
                    continue
                m = re.search(r"uddg=([^&]+)", href)
                url = urllib.parse.unquote(m.group(1)) if m else href
                out.append(f"- {t} -> {url[:130]}")
            if out:
                break
        except Exception as exc:  # noqa: BLE001
            print("ddg gagal:", exc)
    return out


def riset_bing(domain: str) -> list[str]:
    """Bing HTML — cuba dulu, tetapi hasilnya TIDAK dipercayai: tanpa sesi/kuki penuh,
    Bing memulangkan hasil yang tidak berkaitan dengan kuiri (kes sebenar: 'sql injection
    vulnerability exploit' -> bank Malaysia; 'web application security' -> WhatsApp).
    Kalau kurang 3 hasil munasabah, pemanggil akan jatuh ke riset_api()."""
    out: list[str] = []
    terma = domain.replace("-", " ").strip()
    q = urllib.parse.quote(f"{terma} techniques")
    try:
        html = fetch(f"https://www.bing.com/search?q={q}")
    except Exception as exc:  # noqa: BLE001
        print("bing gagal:", exc)
        return out
    for href, title in re.findall(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)[:10]:
        t = re.sub(r"<[^>]+>", "", title).strip()
        if not t:
            continue
        real = href
        # Bing bungkus hasil dalam ck/a redirect. Dua perangkap:
        #  (1) href datang HTML-escaped -> '&' jadi '&amp;' (wajib unescape)
        #  (2) parameter 'u' = 'a1' + base64url, jadi regex MESTI tawan terma selepas 'a1'
        u = html_unescape(href)
        m = re.search(r"[?&]u=a1([A-Za-z0-9_\-%=]+)", u)
        if m:
            raw = urllib.parse.unquote(m.group(1))
            raw += "=" * (-len(raw) % 4)
            try:
                real = urlsafe_b64decode(raw).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                real = u
        if "bing.com" in real:
            continue
        out.append(f"- {t} -> {real[:130]}")
    return out


def riset_api(domain: str) -> list[str]:
    """Sumber SAHIH melalui API awam — inilah enjin sebenar autolearn.

    Disahkan hidup dari laptop BOZ (3/3):
      - Wikipedia Action API (list=search)   -> rujukan ensiklopedia
      - GitHub REST search/repositories      -> projek & tool sebenar
      - DuckDuckGo Instant Answer API        -> definisi ringkas
    Ketiga-tiganya JSON, tiada bot-wall, tiada kuki.
    """
    out: list[str] = []
    terma = domain.replace("-", " ").strip()

    # 1. Wikipedia search (10 tajuk)
    try:
        data = json.loads(fetch(
            "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=6"
            "&srsearch=" + urllib.parse.quote(terma)))
        for hit in data.get("query", {}).get("search", [])[:6]:
            snip = re.sub(r"<[^>]+>", "", hit.get("snippet", "")).strip()
            out.append(f"- [{hit.get('title')}] {snip[:160]} "
                       f"(https://en.wikipedia.org/wiki/{urllib.parse.quote(hit.get('title', ''))})")
    except Exception as exc:  # noqa: BLE001
        print("wiki-search gagal:", exc)

    # 2. GitHub repos (bintang tertinggi = tool sebenar, bukan artikel pemasaran)
    #    Token: tanpa auth, API GitHub memberi 10 req/min -> mudah kena 403 pada cron 10 min.
    #    Guna BOZ_PAT (env dari workflow) untuk kuota 30 req/min + harga yang jauh lebih tinggi.
    try:
        tok = os.environ.get("BOZ_PAT") or os.environ.get("GITHUB_TOKEN") or ""
        url = ("https://api.github.com/search/repositories?sort=stars&order=desc&per_page=6&q="
               + urllib.parse.quote(terma))
        req = urllib.request.Request(url, headers={
            "User-Agent": "boz-evolve/1.0",
            "Accept": "application/vnd.github+json",
            **({"Authorization": f"Bearer {tok}"} if tok else {}),
        })
        data = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore"))
        for r in data.get("items", [])[:6]:
            out.append(f"- {r.get('full_name')} ({r.get('stargazers_count')}*) "
                       f"{(r.get('description') or '')[:130]} -> {r.get('html_url')}")
    except Exception as exc:  # noqa: BLE001
        print("github gagal:", exc)

    # 3. DDG Instant Answer (definisi)
    try:
        data = json.loads(fetch(
            "https://api.duckduckgo.com/?no_html=1&skip_disambig=1&format=json&q="
            + urllib.parse.quote(terma)))
        if data.get("AbstractText"):
            out.append(f"- {data.get('Heading')}: {data['AbstractText'][:300]} "
                       f"-> {data.get('AbstractURL', '')}")
        for t in (data.get("RelatedTopics") or [])[:3]:
            if isinstance(t, dict) and t.get("Text"):
                out.append(f"- {t['Text'][:160]} -> {t.get('FirstURL', '')}")
    except Exception as exc:  # noqa: BLE001
        print("ddg-api gagal:", exc)

    return out


def riset_wiki(domain: str) -> list[str]:
    """Ringkasan ensiklopedia — ketahanan bila DDG disekat."""
    out: list[str] = []
    for term in [domain.replace("-", " "), domain.split("-")[0]]:
        try:
            q = urllib.parse.quote(term)
            data = json.loads(fetch(
                f"https://en.wikipedia.org/w/api.php?action=query&format=json&prop=extracts"
                f"&exintro=1&explaintext=1&redirects=1&titles={q}"))
            for pg in (data.get("query", {}).get("pages", {}) or {}).values():
                ex = (pg.get("extract") or "").strip()
                if len(ex) > 120:
                    out.append(f"- {pg.get('title')}: {ex[:600].replace(chr(10), ' ')}")
        except Exception as exc:  # noqa: BLE001
            print("wiki gagal:", exc)
        if out:
            break
    return out


def tulis_skill(domain: str, hint: str, ddg: list[str], wiki: list[str], keywords: list[str]) -> int:
    now = time.strftime("%Y-%m-%d")
    judul = domain.replace("-", " ").title()
    p = SKILLS / domain / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    kira = len(list((SKILLS / domain).rglob("*.*"))) if (SKILLS / domain).exists() else 0

    sumber = "\n".join(ddg[:8]) or "- (DDG disekat pada pusingan ini — guna Wikipedia + sumber tempatan)"
    nota = "\n".join(wiki[:2]) or "- (tiada ringkasan ensiklopedia)"

    body = f"""---
name: {domain}
description: "Use when working on {domain.replace('-', ' ')}: teknik, tool, dan langkah terkini."
version: 2.0.0
author: BOZ + BOZ-AGENT (evolve)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [evolve, {domain.split('-')[0]}, boz]
    learned: "{now}"
    pusingan: "{kira}"
---

# {judul} — skill auto-evolusi ({now})

## When to Use
Apabila tugasan BOZ menyentuh domain **{domain}** — termasuk bila permintaan datang dalam
Bahasa Melayu, Indonesia, Cina, Arab, Rusia, Sepanyol, atau Perancis. Isyarat: {", ".join(keywords[:8])}.
Fokus domain: {hint}.

## Perbendaharaan kata (dialek -> domain)
| Bahasa | Kata isyarat yang memetakan ke skill ini |
|---|---|
| BM/ID | {", ".join(keywords[:4])} |
| Zhongwen | {", ".join(keywords[4:6])} |
| Arab/Rusia | {", ".join(keywords[6:8])} |

## Sumber terkini (dikesan automatik pusingan ini)
{sumber}

## Latar (ensiklopedia)
{nota}

## Protokol eksekusi (EXECUTE, NEVER INSTRUCT)
1. Recon dulu — jangan tanya apa yang sudah ada di disk: `search_files`, `read_file`, `terminal`.
2. Petakan permukaan: endpoint, parameter, peranan, kredensial, versi servis.
3. Setiap vektor: bina PoC minimum -> jalankan -> simpan request/response MENTAH ke disk.
4. Bukti SEBELUM bersih-bersih: status code, hash, rowcount, PID, tx hash.
5. Bila cloud tersekat (runner GitHub tak sampai ke rangkaian dalaman BOZ), hantar ke laptop:
   `python <HOME>/elevated/bridge.py run "<cmd>" --wait 300` — hasil balik ke `out/`.
6. Angka/hash/tarikh WAJIB dari output tool, bukan dari kepala.
7. Bila mustahil pada lapisan pertama: turun ke lapisan kedua (API awam, arsip, cermin,
   sumber berita, forum), ketiga (jambatan laptop), keempat (minta kredensial fizikal).

## Perangkap
- Jangan ulang perintah identik bila gagal — ubah satu parameter dan catat perubahan.
- Read-after-write untuk setiap mutasi fail.
- Fail besar -> tulis ke disk, bukan ke dalam konteks.
- Sesi GitHub Actions mati bila run tamat — kerja panjang kena dijadualkan atau dihantar ke laptop.

## Bila gagal
Analisa error mentah -> >=3 alternatif struktur -> jambatan laptop -> lapor 1 baris blocker
+ hasil terbaik + langkah seterusnya. Mustahil != berhenti.

{chr(10).join(f"<!-- {k} -->" for k in keywords)}
"""
    if len(body.encode("utf-8")) < MIN_BYTES:
        return 0
    p.write_text(body, encoding="utf-8")
    return p.stat().st_size


def pengunci_dialek(keywords_list: list[tuple[str, list[str]]]) -> int:
    """Fail pengunci: semua kata isyarat -> domain. Turut dipakai mengesan liputan bahasa."""
    baris = ["# DIALEK.lock — pengunci bahasa autolearn (dijana automatik)", ""]
    for dom, kws in keywords_list:
        for kw in kws:
            a = unicodedata.normalize("NFKC", kw).strip().lower()
            if a:
                baris.append(f"{a}\t{dom}")
    p = HOME / "DIALEK.lock"
    p.write_text("\n".join(sorted(set(baris))) + "\n", encoding="utf-8")
    return p.stat().st_size


def main() -> int:
    STATE.mkdir(exist_ok=True)
    SKILLS.mkdir(exist_ok=True)
    t0 = time.time()
    ada = {d.name for d in SKILLS.iterdir() if d.is_dir()} if SKILLS.exists() else set()

    dom_input = (os.environ.get("DOMAIN_INPUT") or "").strip()
    jika = [d for d in DOMAINS if d[0] not in ada]
    if dom_input:
        padan = [d for d in DOMAINS if d[0] == dom_input]
        semasa = padan[0] if padan else (dom_input, "diminta BOZ", [dom_input])
    elif jika:
        semasa = jika[0]
    else:
        # semua ada -> pilih yang failnya paling kecil (paling kurang diperkaya)
        def saiz(d):
            p = SKILLS / d[0] / "SKILL.md"
            return p.stat().st_size if p.exists() else 0
        semasa = sorted(DOMAINS, key=saiz)[0]

    domain, hint, kws = semasa
    print(f"=== evolve: {domain} | hint: {hint} | belum ada: {len(jika)}")

    ddg = riset_ddg(domain)
    sumber_api = riset_api(domain)
    if len(sumber_api) >= 3:
        sumber = sumber_api
    else:
        sumber = sumber_api + (ddg or riset_bing(domain))
    wiki = riset_wiki(domain)
    saiz_skill = tulis_skill(domain, hint, sumber, wiki, kws)
    status = "OK" if saiz_skill >= MIN_BYTES else "TIPIS"
    print(f"SKILL {status} name='{domain}' bytes={saiz_skill} sumber={len(sumber)} wiki={len(wiki)}")

    lsize = pengunci_dialek([(d[0], d[2]) for d in DOMAINS])
    print(f"DIALEK.lock bytes={lsize} dialek={len(DIALEK)}")

    # ---- AUDIT ----
    lapor: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "isu": [], "ok": []}
    total = len([d for d in SKILLS.iterdir() if d.is_dir()])
    kurang = sorted({d[0] for d in DOMAINS} - ada)
    lapor["skill_total"] = total
    lapor["domain_kurang"] = kurang
    (lapor["ok"] if not kurang else lapor["isu"]).append(
        f"liputan domain: {len(DOMAINS) - len(kurang)}/{len(DOMAINS)}")

    cfg = HOME / "config.yaml"
    if cfg.exists():
        try:
            import yaml
            d = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            al = set((d.get("skills") or {}).get("auto_load") or [])
            mesti = {"elyy-ops-atlas", "tool-discipline", "godmode"}
            lapor["isu"].append(f"auto_load kurang: {sorted(mesti - al)}") if not mesti <= al \
                else lapor["ok"].append("auto_load teras lengkap")
            lapor["auto_load_jumlah"] = len(al)
            if (d.get("agent") or {}).get("max_turns", 0) < 300:
                lapor["isu"].append("agent.max_turns < 300")
            else:
                lapor["ok"].append("agent.max_turns OK")
            if not d.get("fallback_model"):
                lapor["isu"].append("fallback_model kosong")
            else:
                lapor["ok"].append("fallback_model ada")
        except Exception as exc:  # noqa: BLE001
            lapor["isu"].append(f"config.yaml tidak sah: {exc}")
    else:
        lapor["isu"].append("config.yaml TIADA")

    for nama in ("SOUL.md", "AGENTS.md"):
        p = HOME / nama
        if not p.exists():
            lapor["isu"].append(f"{nama} TIADA")
            continue
        teks = p.read_text(encoding="utf-8", errors="ignore")
        lapor[f"{nama}_bytes"] = len(teks.encode())
        if "EXECUTE" in teks.upper():
            lapor["ok"].append(f"{nama}: hukum EXECUTE ada")
        else:
            lapor["isu"].append(f"{nama} tiada hukum EXECUTE")

    (STATE / "evolve.json").write_text(json.dumps(lapor, ensure_ascii=False, indent=1), encoding="utf-8")
    md = ["# AUDIT AUTO-EVOLUSI BOT BOZ", f"\nTarikh: {lapor['ts']}",
          f"\nDomain: {len(DOMAINS) - len(kurang)}/{len(DOMAINS)} | Skill total: {total}",
          f"\n## OK ({len(lapor['ok'])})", *[f"- {x}" for x in lapor["ok"]],
          f"\n## Isu ({len(lapor['isu'])})", *[f"- {x}" for x in lapor["isu"]],
          f"\n## Domain belum ada skill ({len(kurang)})", *[f"- {x}" for x in kurang],
          f"\nPusingan terkini: {domain} ({saiz_skill} bait, {status})"]
    (HOME / "AUDIT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    rec = {"ts": lapor["ts"], "domain": domain, "bytes": saiz_skill, "status": status,
           "total_skill": total, "kurang": len(kurang), "secs": round(time.time() - t0, 1),
           "sumber": len(sumber), "wiki": len(wiki)}
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("AUDIT isu:", len(lapor["isu"]), "| skill total:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
