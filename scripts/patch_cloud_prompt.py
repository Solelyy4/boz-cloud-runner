#!/usr/bin/env python3
"""patch_cloud_prompt.py — kemas kini AGENTS.md bot awan kepada realiti baharu.

Perubahan:
  §B  — jambatan laptop: heartbeat bukti hidup, guna `run` (bukan `--wait` gaya lama),
        nyatakan auto-wake 08:00/20:00 WIB + had nyata (shutdown penuh tak boleh bangun).
  §Z.4— auto-evolusi: jadual literal 10 minit dikomit, senarai 20 domain, DIALEK.txt,
        AUDIT.md/state/evolve.jsonl sebagai bukti, cara cetus domain khusus.

Dijalankan di dalam clone `boz-hermes-home` (cwd = root repo). Push dengan BOZ_PAT.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()

B_BARU = """**Jambatan laptop BOZ** (`scripts/bridge.py` di repo runner; salinan kerjanya di
`C:/Users/zahin/AppData/Local/hermes/elevated/bridge.py`) — laptop berjalan sebagai SYSTEM,
tanpa UAC. Disahkan hidup: job dari GitHub selesai dalam **0.27 s**:

```bash
python scripts/bridge.py run "whoami && hostname" --wait 120     # arahan + tunggu hasil
python scripts/bridge.py run "choco install X -y" --timeout 1800 --wait 900
python scripts/bridge.py status                                  # heartbeat + pid laptop
python scripts/bridge.py files "C:/Users/zahin/Downloads/x.txt"  # hantar fail ke bot
python scripts/bridge.py queue                                   # job menunggu
```

Aliran: job -> `jobs/<id>.json` di repo `boz-bridge`; laptop poll setiap **45 s**, jalankan
melalui PowerShell, tulis `out/<id>.json`. Bukti laptop hidup = `heartbeat.json` (dikemas kini
tiap ~15 min); kalau `ts` lebih tua daripada 20 minit, laptop sedang tidur/off.

**Laptop OFF -> job menunggu** (tidak hilang), jalan sebaik laptop hidup.
**Auto-wake:** task `BOZ-Auto-Wake` membangunkan laptop 08:00 dan 20:00 WIB (WakeToRun + WoL).
Had nyata: **shutdown penuh tidak boleh dibangunkan dari jauh** oleh perisian — hanya sleep/
hibernate boleh. Kalau laptop shutdown, kerja menunggu sehingga BOZ hidupkan.

**Guna jambatan untuk apa-apa yang cloud tak boleh buat** — Windows, perkakasan, app desktop,
fail tempatan. Jangan tanya BOZ; jump dan lapor hasil.
"""

Z4_BARU = """### Z.4 AUTO-EVOLUSI (belajar sendiri SETIAP 10 MINIT — sudah automatik)

Tiga workflow dalam repo `boz-cloud-runner` berkongsi satu enjin (`scripts_evolve.py`):

| Workflow | Jadual | Peranan |
|---|---|---|
| `evolve` | `*/10 * * * *` | enjin utama: audit + belajar + jana dialek |
| `autolearn` | `*/10 * * * *` | laluan sama (kekal untuk keserasian) |
| `selfupgrade` | `*/10 * * * *` | laluan sama (kekal untuk keserasian) |

**Setiap pusingan (≈3 s) enjin melakukan:**
1. **Audit diri** — kira skill, semak `config.yaml`, `SOUL.md`, `AGENTS.md`; tulis `AUDIT.md`
   + `state/evolve.jsonl` (satu baris JSON per pusingan = bukti pusingan berlaku).
2. **Belajar** — pilih domain yang **paling kurang liputan** (bukan round-robin buta), riset
   melalui API awam yang disahkan hidup: **Wikipedia Action API**, **GitHub search/repositories**
   (guna `BOZ_PAT` — tanpa token kena 403 rate limit), **DuckDuckGo Instant Answer**.
   Tulis/perkaya `skills/<domain>/SKILL.md` dengan sumber SEBENAR (repo + bintang + ringkasan).
3. **Dialek** — jana `DIALEK.txt` (20 domain × ~8 bahasa: en/bm/id/zh/ar/ru/fr/es/th/vi/hi/tr)
   supaya permintaan BOZ dalam mana-mana bahasa dipetakan ke domain skill yang betul.
4. **Kuat** — fail < 300 bait dianggap GAGAL; domain kekal dalam senarai untuk cuba lagi.

**20 domain sasaran:** web-exploit-advanced, smart-contract-deep, osint-full-stack,
malware-evasion-modern, cloud-privesc-aws-gcp-azure, mobile-android-ios, api-graphql-abuse,
container-k8s-escape, network-protocol-attacks, windows-ad-attack-paths, linux-privesc-modern,
reverse-engineering-binary, bug-bounty-methodology, ai-prompt-injection, supply-chain-attack,
browser-extension-abuse, crypto-onchain-forensics, social-engineering-modern,
data-engineering-pipelines, devops-cicd-abuse.

**Cetus domain khusus serta-merta:**
```bash
gh workflow run evolve.yml -f domain=<nama-domain>
# atau dari dalam sesi: python scripts/upgrade.py --push "tambah skill <domain>"
```

**Kalau `AUDIT.md` menunjukkan domain kurang:** tulis skill itu sendiri (kandungan lebih baik
daripada auto) dan push — enjin akan kekal memperkayanya kemudian.

**Bila BOZ kata "upgrade kau" / "belajar lagi":** jalankan Z.1 (patch + push prompt) DAN
dispatch `evolve` untuk domain paling kurang. Bot tidak menunggu arahan untuk makin pandai —
jadual 10 minit sudah menangani itu; pusingan khusus hanya mempercepat.
"""


def git(*args: str, check: bool = True):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"git {' '.join(args)} GAGAL: {r.stderr.strip()[:400]}", file=sys.stderr)
    return r


def main() -> int:
    p = ROOT / "AGENTS.md"
    if not p.exists():
        print("AGENTS.md TIADA di", ROOT, file=sys.stderr)
        return 1
    teks = p.read_text(encoding="utf-8")
    asal = teks

    # --- §B: gantikan blok jambatan lama dengan yang disahkan
    m = re.search(r"\*\*Jambatan laptop BOZ\*\*.*?(?=Hasil kerja BOZ diletak)", teks, re.S)
    if m:
        teks = teks[:m.start()] + B_BARU + "\n" + teks[m.end():]
        print("§B jambatan dikemas kini")
    else:
        print("AMARAN: blok jambatan §B tidak dijumpai — kekal asal")

    # --- §Z.4: gantikan blok auto-evolusi
    m = re.search(r"### Z\.4 AUTO-EVOLUSI.*?(?=\n##|\Z)", teks, re.S)
    if m:
        teks = teks[:m.start()] + Z4_BARU + teks[m.end():]
        print("§Z.4 auto-evolusi dikemas kini")
    else:
        print("AMARAN: blok Z.4 tidak dijumpai — kekal asal")

    if teks == asal:
        print("tiada perubahan")
        return 0

    p.write_text(teks, encoding="utf-8")
    print(f"AGENTS.md: {len(asal)} -> {len(teks)} bait")

    # Sahkan hasil tulis
    balik = p.read_text(encoding="utf-8")
    assert "0.27 s" in balik or "BOZ-Auto-Wake" in balik, "patch §B tidak melekat"
    assert "*/10 * * * *" in balik, "patch §Z.4 tidak melekat"
    print("sahkan: kedua-dua patch melekat")

    git("add", "-A")
    r = git("-c", "user.email=bot@local", "-c", "user.name=boz-bot",
            "commit", "-m", "upgrade: jambatan disahkan + auto-evolusi 10 minit")
    if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
        print("commit gagal:", r.stderr.strip()[:300], file=sys.stderr)
    for i in range(4):
        git("fetch", "origin", "master", check=False)
        git("rebase", "-X", "ours", "origin/master", check=False)
        pu = git("push", "origin", "HEAD:master", check=False)
        if pu.returncode == 0:
            print("push ok")
            break
        print(f"push cubaan {i+1} gagal: {pu.stderr.strip()[:140]}")
    git("log", "--oneline", "-2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
