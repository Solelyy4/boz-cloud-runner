#!/usr/bin/env python3
"""
Betulkan skills.auto_load dalam config.yaml (boz-hermes-home).

Masalah sebenar dari gw_trace.log:
  skills.auto_load: skill(s) not found or disabled, skipped:
  security, web, software-development, autonomous-ai-agents, telekey-bot-ops,
  research, productivity
→ 'security', 'web', dll ialah FOLDER KATEGORI (tiada SKILL.md sendiri),
  jadi auto_load menolaknya. Bot jadi buta kepada domain sebenar.

Pendekatan TEKS: cari blok `skills:\n  auto_load:\n    - ...` dan ganti senarai.
Selamat: .bak, sahkan kunci penting + saiz, read-after-write.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

GH = r"C:/Users/zahin/AppData/Local/hermes/bin/gh.exe"
REPO = "Solelyy4/boz-hermes-home"
PATH_IN_REPO = "config.yaml"

# Skill peringkat atas yang SAH (ada SKILL.md). Kategori diganti subskill sebenar.
AUTO_LOAD = [
    # Teras identiti & disiplin
    "cari-luar-telegram", "elyy-ops-atlas", "tool-discipline", "godmode",
    # Bounty & pentest (tugasan BOZ utama)
    "bug-bounty-pipeline", "bug-bounty-methodology", "pentest-web-quickstart",
    "recon-surface-map", "variant-discovery", "exploitability-analyzer",
    "evidence-first-report", "bounty-autopilot",
    # Domain teknikal
    "web-exploit-advanced", "api-graphql-abuse", "ai-prompt-injection",
    "anti-bot-http-ladder", "blocked-page-recovery", "captcha-solver",
    "smart-contract-audit", "smart-contract-deep", "blockchain-cli-patterns",
    "osint-full-stack", "malware-evasion-modern", "supply-chain-attack",
    "reverse-engineering-binary", "network-protocol-attacks",
    # Infra & ops
    "9router-gateway-ops", "telekey-bot-ops", "hermes-agent", "windows-bash-ops",
    "free-llm-api-keys", "github", "github-grab", "systematic-debugging",
]


def gh(*args, input_data=None):
    return subprocess.run([GH, *args], capture_output=True, text=True,
                          input=input_data, encoding="utf-8")


def main():
    r = gh("api", f"repos/{REPO}/contents/{PATH_IN_REPO}", "--jq", ".content")
    if r.returncode != 0:
        print("GAGAL ambil config:", r.stderr[:300]); return 1
    content = base64.b64decode(r.stdout.strip() + "\n").decode("utf-8")
    sha = gh("api", f"repos/{REPO}/contents/{PATH_IN_REPO}", "--jq", ".sha").stdout.strip()
    print(f"config asal: {len(content.encode())} bait, sha={sha[:12]}")
    Path("config_cloud.bak2.yaml").write_text(content, encoding="utf-8")

    # Ganti blok auto_load sahaja
    pat = re.compile(r"(  auto_load:\n)((?:    - [^\n]*\n)+)", re.M)
    m = pat.search(content)
    if not m:
        print("GAGAL: blok skills.auto_load tidak dijumpai"); return 1
    lama = m.group(2).count("\n")
    baru = "".join(f"    - {s}\n" for s in AUTO_LOAD)
    content_baru = content[:m.start(2)] + baru + content[m.end(2):]
    print(f"auto_load: {lama} -> {len(AUTO_LOAD)} skill")

    for kunci in ("model:", "providers:", "platforms:", "fallback_model:",
                  "channel_prompts:", "skills:", "auto_load:"):
        if kunci not in content_baru:
            print(f"GAGAL: kunci '{kunci}' hilang"); return 1
    if len(content_baru.encode()) < 3000:
        print("GAGAL: config terlalu kecil"); return 1
    print(f"config baharu: {len(content_baru.encode())} bait")

    payload = json.dumps({
        "message": "fix(skills): auto_load guna skill sebenar, bukan folder kategori",
        "sha": sha, "branch": "master",
        "content": base64.b64encode(content_baru.encode()).decode(),
    })
    r2 = gh("api", "-X", "PUT", f"repos/{REPO}/contents/{PATH_IN_REPO}",
            "--input", "-", input_data=payload)
    if r2.returncode != 0:
        print("GAGAL push:", r2.stderr[:400]); return 1
    print("PUSH OK")
    try:
        print("commit:", json.loads(r2.stdout)["commit"]["sha"][:12])
    except Exception:
        pass

    r3 = gh("api", f"repos/{REPO}/contents/{PATH_IN_REPO}", "--jq", ".content")
    semula = base64.b64decode(r3.stdout.strip() + "\n").decode("utf-8")
    m2 = pat.search(semula)
    jumlah = m2.group(2).count("\n") if m2 else 0
    ok = jumlah == len(AUTO_LOAD) and "    - security\n" not in semula
    print("SAHKAN baca-semula:", "LULUS" if ok else "GAGAL")
    print(f"  auto_load sekarang: {jumlah} skill")
    print("  folder kategori buang:", "    - security\n" not in semula)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
