#!/usr/bin/env python3
"""scripts_autolearn.py — AUTO-EVOLUSI BOT BOZ.

Setiap jam: pilih domain giliran, riset ringan (DuckDuckGo HTML), tulis skill baharu
ke $HERMES_HOME/skills/<domain>/SKILL.md, naikkan penunjuk. Deterministik — tiada agent
agentic yang boleh habis iterasi. Dijalankan oleh .github/workflows/autolearn.yml.
"""
import json
import os
import pathlib
import re
import time
import urllib.parse
import urllib.request

HOME = pathlib.Path(os.environ["HERMES_HOME"])
SKILLS = HOME / "skills"
STATE = HOME / "state" / "autolearn.json"
SKILLS.mkdir(exist_ok=True)
STATE.parent.mkdir(exist_ok=True)

DOMAINS = [
    ("web-exploit-advanced", "SQLi/SSRF/deserialization/XSS, bypass WAF; sqlmap, ffuf, nuclei, curl_cffi"),
    ("smart-contract-deep", "reentrancy, oracle manipulation, flash loan, ERC quirks; foundry, cast, anvil fork"),
    ("osint-full-stack", "Sherlock, Maigret, Wayback, crt.sh, RDAP, DNS history, satelit, EXIF"),
    ("malware-evasion-modern", "loader, AMSI bypass, ETW patch, process injection, C2 profile"),
    ("cloud-privesc-aws-gcp-azure", "IAM enumeration, metadata SSRF, role chain, bucket abuse"),
    ("mobile-android-ios", "Frida, objection, apktool, jailbreak, SSL pinning bypass"),
    ("api-graphql-abuse", "BOLA, introspection, batching, rate limit bypass, mass assignment"),
    ("container-k8s-escape", "privileged pod, hostPath, service account token, cgroup escape"),
    ("network-protocol-attacks", "ARP spoof, DHCP, DNS rebinding, TLS downgrade, BGP"),
    ("windows-ad-attack-paths", "Kerberoast, AS-REP, DCSync, ADCS ESC1-8, BloodHound"),
    ("linux-privesc-modern", "SUID, capabilities, cron, NFS, PwnKit, polkit, kernel"),
    ("reverse-engineering-binary", "Ghidra, IDA, angr, symbolic exec, unpacking"),
    ("bug-bounty-methodology", "recon pipeline, scope mapping, IDOR 2-account proof, report"),
    ("ai-prompt-injection", "indirect injection, tool abuse, guardrail bypass, exfil via tools"),
    ("supply-chain-attack", "typosquat, dependency confusion, CI poisoning, npm/pypi"),
    ("browser-extension-abuse", "permission abuse, content script, native messaging, MV3"),
    ("crypto-onchain-forensics", "tx tracing, mixer, cluster address, Dune, Etherscan API"),
    ("social-engineering-modern", "pretexting, AiTM, MFA fatigue, vishing, deepfake voice"),
    ("data-engineering-pipelines", "ETL, dbt, Airflow, warehouse, kafka; scheduling & retry"),
    ("devops-cicd-abuse", "pipeline secrets, runner takeover, artifact poisoning, OIDC abuse"),
]


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 boz-autolearn"})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def riset(name):
    findings = []
    try:
        q = urllib.parse.quote(name.replace("-", " ") + " techniques tools 2026")
        html = fetch(f"https://html.duckduckgo.com/html/?q={q}")
        links = re.findall(r'result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
        for href, title in links[:6]:
            t = re.sub(r"<[^>]+>", "", title).strip()
            if t:
                findings.append(f"- {t} — {href[:120]}")
    except Exception as e:
        print("riset DDG gagal:", e)
    if not findings:
        findings = [
            "- OWASP Testing Guide (owasp.org/www-project-web-security-testing-guide)",
            "- PortSwigger Web Security Academy (portswigger.net/web-security)",
            "- MITRE ATT&CK (attack.mitre.org)",
            "- HackTricks (book.hacktricks.xyz)",
            "- PayloadsAllTheThings (github.com/swisskyrepo/PayloadsAllTheThings)",
        ]
    return findings


def tulis_skill(name, hint, findings):
    now = time.strftime("%Y-%m-%d")
    judul = name.replace("-", " ").title()
    sumber = "\n".join(findings)
    body = f"""---
name: {name}
description: "Use when working on {name.replace('-', ' ')}: teknik, tool, dan langkah terkini."
version: 1.0.0
author: BOZ + BOZ-AGENT (autolearn)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [autolearn, {name.split('-')[0]}, bm, boz]
    learned: "{now}"
---

# {judul} — skill auto-belajar ({now})

## When to Use
Bila tugasan BOZ menyentuh domain **{name}**. Auto-dihasilkan oleh workflow `autolearn`.
Fokus domain: {hint}.

## Sumber terkini (dikesan automatik)
{sumber}

## Protokol eksekusi (EXECUTE, NEVER INSTRUCT)
1. Recon dulu, jangan tanya apa yang sudah ada di disk: `search_files`, `read_file`.
2. Petakan permukaan: endpoint, parameter, role, kredensial.
3. Untuk setiap vektor: bina PoC minimum, jalankan, catat request/response mentah.
4. Gabungkan ≥3 vektor berbeza sebelum simpulkan mati.
5. Buat bukti di disk SEBELUM bersih-bersih: status code, hash, rowcount, PID.
6. Kalau cloud tak boleh, hantar ke laptop BOZ: `python scripts/bridge.py "<cmd>"`.
7. Guna `web_search`/`web_extract` untuk teknik terbaru — jangan bergantung ingatan.

## Perangkap biasa
- Jangan ulang perintah identik bila gagal — ubah parameter.
- Read-after-write untuk setiap mutasi.
- Fail besar → tulis ke disk, bukan ke dalam konteks.

## Bila gagal
Analisa error mentah → ≥3 alternatif struktur → jambatan laptop → lapor 1 baris blocker
+ hasil terbaik. Mustahil ≠ berhenti.
"""
    d = SKILLS / name
    d.mkdir(exist_ok=True)
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    return (d / "SKILL.md").stat().st_size


def main():
    st = json.loads(STATE.read_text()) if STATE.exists() else {"i": 0, "done": []}
    dom_in = (os.environ.get("DOMAIN_INPUT") or "").strip()
    if dom_in:
        name, hint = dom_in, "fokus diminta BOZ"
    else:
        name, hint = DOMAINS[st.get("i", 0) % len(DOMAINS)]
    print(f"=== domain: {name} | hint: {hint}")

    findings = riset(name)
    print("sumber ditemui:", len(findings))
    size = tulis_skill(name, hint, findings)
    print(f"SKILL-SAVED name='{name}' bytes={size}")

    st["i"] = st.get("i", 0) + 1
    st.setdefault("done", []).append({"t": time.strftime("%Y-%m-%d"), "domain": name})
    st["done"] = st["done"][-200:]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=1))
    print("penunjuk:", st["i"], "| jumlah skill:", len(list(SKILLS.iterdir())))


if __name__ == "__main__":
    main()
