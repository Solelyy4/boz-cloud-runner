#!/usr/bin/env python3
"""semak_kebersihan.py — gerbang kualiti untuk repo bot.

Mengesan corak yang pernah MENYEBABKAN bot bisu. Setiap semakan ada bukti sejarahnya.
Keluar 1 = ada pelanggaran, jangan dispatch.

Guna: python scripts/semak_kebersihan.py [root]
"""
from __future__ import annotations

import os
import re
import sys

# (nama, corak, ruang fail, maksimum dibenarkan, sebab)
SEMAK = [
    (
        "getUpdates di luar gateway",
        re.compile(r"\bgetUpdates\s*[?\"']"),
        (".yml", ".yaml", ".py", ".sh"),
        0,
        "Merampas long-poll -> 409 -> adapter PARKED -> bot bisu.",
    ),
    (
        "cancel-in-progress: true",
        re.compile(r"cancel-in-progress:\s*true", re.I),
        (".yml", ".yaml"),
        0,
        "Setiap dispatch membunuh run hidup. Sejarah: 12 run cancelled berturut.",
    ),
    (
        "pgrep -f (bunuh diri sendiri)",
        re.compile(r"pgrep\s+-f"),
        (".sh",),
        0,
        "pgrep -f memadankan skrip sendiri -> rc=127 setiap kali.",
    ),
    (
        "reasoning_effort berperingkat",
        re.compile(r"^\s*reasoning_effort:\s*(low|medium|high|false)\s*$", re.M),
        (".yml", ".yaml"),
        0,
        "HTTP 400 pada model kecil -> rantai fallback habis -> bot bisu.",
    ),
    (
        "model reput dalam rantaian",
        re.compile(r"(open-mistral-nemo|pixtral-12b-latest|mistral-medium-latest)"),
        (".yaml",),
        0,
        "TIADA dalam akaun / 429. Rantaian fallback reput.",
    ),
    (
        "s3cr3t dalam fail (bocor)",
        re.compile(r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|\d{9,10}:AA[A-Za-z0-9_-]{30,})"),
        (".py", ".sh", ".yml", ".yaml", ".md"),
        0,
        "Token/kunci tidak boleh masuk repo awam.",
    ),
    (
        "python3 sistem dalam skrip gateway",
        re.compile(r"^\s*(?:\"[^\"]*\$\{?GWPY|\$GWPY|python3)\s+scripts/", re.M),
        (".sh",),
        0,
        "Runner Ubuntu tiada modul venv -> peronda mati senyap, bukti rangkaian hilang.",
    ),
    (
        "max_tokens terlalu kecil (model reasoning)",
        re.compile(r"\"max_tokens\"\s*:\s*(\d{1,3})\s*[,}]"),
        (".py",),
        0,
        "gpt-oss habiskan kuota pada `reasoning` -> content='' (diukur: 60 -> 3/4 gagal).",
    ),
    (
        "import yaml tanpa perlindungan",
        re.compile(r"^\s{0,4}import yaml\s*$", re.M),
        (".py",),
        1,
        "Runner tiada PyYAML -> ModuleNotFoundError -> bot tidak mula (run 42436126082).",
    ),
]

DILANGKAU = {".git", "node_modules", "__pycache__", "ujian", "bukti", "cari"}

# Ambang: nilai max_tokens di bawah ini pada model reasoning = jawapan kosong.
MIN_TOKENS = 200


def jalan(root: str) -> int:
    langgar = 0
    diperiksa = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DILANGKAU]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            with open(path, encoding="utf-8", errors="replace") as f:
                teks = f.read()
            for nama, corak, ext_sah, maks, sebab in SEMAK:
                if ext not in ext_sah:
                    continue
                diperiksa += 1
                # Buang komen supaya rujukan dokumentasi tidak dikira panggilan.
                bersih = "\n".join(
                    line for line in teks.splitlines()
                    if not line.lstrip().startswith(("#", "//", "*"))
                )
                padan = corak.findall(bersih)
                if nama.startswith("max_tokens"):
                    # Bandingkan NILAI, bukan bilangan padanan.
                    kecil = [p for p in padan if int(p) < MIN_TOKENS]
                    if kecil:
                        langgar += 1
                        print(f"[LANGAR] {rel}: {nama} {kecil} — {sebab}")
                    continue
                if len(padan) > maks:
                    langgar += 1
                    print(f"[LANGAR] {rel}: {nama} ({len(padan)}x) — {sebab}")
                    for m in padan[:3]:
                        print(f"          padan: {m if isinstance(m, str) else m}")

    print(f"\ndan fail diperiksa: {diperiksa} semakan")
    if diperiksa == 0:
        # Gagal KERAS bila tiada apa diperiksa. Bukti: ujian dengan direktori salah
        # melaporkan "BERSIH" tanpa memeriksa satu fail pun — hijau palsu.
        print("HASIL: TIADA FAIL DIPERIKSA — ini BUKAN lulus, ini buta")
        return 2
    if langgar:
        print(f"HASIL: {langgar} PELANGGARAN — jangan dispatch")
        return 1
    print("HASIL: BERSIH — selamat dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(jalan(sys.argv[1] if len(sys.argv) > 1 else "."))
