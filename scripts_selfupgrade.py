#!/usr/bin/env python3
"""scripts_selfupgrade.py — SELF-UPGRADE BOT BOZ (mingguan).

Audit + naik taraf diri sendiri:
1. Kira skill yang ada vs senarai domain autolearn → lapor jurang.
2. Pastikan config.yaml sihat (auto_load lengkap, max_turns besar, fallback ada).
3. Pastikan SOUL.md + AGENTS.md versi betul + mengandungi hukum EXECUTE.
4. Tulis laporan ke state/selfupgrade.json + AUDIT.md.
Tiada panggilan API luar — deterministik & pantas.
"""
import json
import os
import pathlib
import re
import time

HOME = pathlib.Path(os.environ["HERMES_HOME"])
SKILLS = HOME / "skills"
STATE = HOME / "state"

# Senarai domain sasaran (mesti padan scripts_autolearn.py)
DOMAINS = [
    "web-exploit-advanced", "smart-contract-deep", "osint-full-stack",
    "malware-evasion-modern", "cloud-privesc-aws-gcp-azure", "mobile-android-ios",
    "api-graphql-abuse", "container-k8s-escape", "network-protocol-attacks",
    "windows-ad-attack-paths", "linux-privesc-modern", "reverse-engineering-binary",
    "bug-bounty-methodology", "ai-prompt-injection", "supply-chain-attack",
    "browser-extension-abuse", "crypto-onchain-forensics", "social-engineering-modern",
    "data-engineering-pipelines", "devops-cicd-abuse",
]


def satu_laporan():
    STATE.mkdir(exist_ok=True)
    lapor = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "isu": [], "ok": []}

    # 1. Skill coverage
    ada = {p.name for p in SKILLS.iterdir() if p.is_dir()} if SKILLS.exists() else set()
    auto = set(DOMAINS)
    kurang = sorted(auto - ada)
    lapor["skill_total"] = len(ada)
    lapor["domain_kurang"] = kurang
    (lapor["ok"] if not kurang else lapor["isu"]).append(
        f"skill coverage: {len(ada)} ada, {len(kurang)} domain belum ada skill"
    )

    # 2. config.yaml
    cfg = HOME / "config.yaml"
    if cfg.exists():
        try:
            import yaml
            d = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            al = set((d.get("skills") or {}).get("auto_load") or [])
            mesti = {"elyy-ops-atlas", "tool-discipline", "godmode"}
            if not mesti.issubset(al):
                lapor["isu"].append(f"auto_load kurang: {sorted(mesti - al)}")
            else:
                lapor["ok"].append("auto_load lengkap")
            if (d.get("agent") or {}).get("max_turns", 0) < 300:
                lapor["isu"].append("agent.max_turns < 300")
            else:
                lapor["ok"].append("agent.max_turns OK")
            if not d.get("fallback_model"):
                lapor["isu"].append("fallback_model kosong")
            else:
                lapor["ok"].append("fallback_model ada")
        except Exception as e:
            lapor["isu"].append(f"config.yaml tidak sah: {e}")
    else:
        lapor["isu"].append("config.yaml TIADA")

    # 3. SOUL / AGENTS
    for nama in ("SOUL.md", "AGENTS.md"):
        p = HOME / nama
        if not p.exists():
            lapor["isu"].append(f"{nama} TIADA")
            continue
        teks = p.read_text(encoding="utf-8", errors="ignore")
        if "EXECUTE" not in teks.upper():
            lapor["isu"].append(f"{nama} tiada hukum EXECUTE")
        else:
            lapor["ok"].append(f"{nama}: hukum EXECUTE ada")
        m = re.search(r"v(\d+)", teks.split("\n", 1)[0])
        lapor[f"{nama}_versi"] = m.group(1) if m else "?"

    # 4. Tulis laporan
    (STATE / "selfupgrade.json").write_text(json.dumps(lapor, ensure_ascii=False, indent=1))
    md = ["# AUDIT SELF-UPGRADE BOT BOZ", f"\nTarikh: {lapor['ts']}",
          f"\n## OK ({len(lapor['ok'])})", *[f"- {x}" for x in lapor["ok"]],
          f"\n## Isu ({len(lapor['isu'])})", *[f"- {x}" for x in lapor["isu"]],
          f"\n## Domain belum ada skill ({len(kurang)})", *[f"- {x}" for x in kurang]]
    (HOME / "AUDIT.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    print("=== SELF-UPGRADE AUDIT ===")
    print(f"skill: {lapor['skill_total']} | isu: {len(lapor['isu'])} | domain kurang: {len(kurang)}")
    for x in lapor["isu"]:
        print(" ISU:", x)
    for x in lapor["ok"]:
        print(" OK :", x)
    return len(lapor["isu"])


if __name__ == "__main__":
    n = satu_laporan()
    print("jumlah isu:", n)
