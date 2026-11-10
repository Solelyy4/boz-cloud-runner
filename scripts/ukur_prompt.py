#!/usr/bin/env python3
"""ukur_prompt.py — ukur saiz prompt bot SEBELUM ia melebihi siling konteks.

MENGAPA INI ADA
===============
Bot BOZ membalas mesej `Hello` dengan:

    400: This model's maximum context length is 32768 tokens. However, you
    requested 2048 output tokens and your prompt contains at least 30721
    input tokens, for a total of at least 32769 tokens.

Kita tersalah sangka ini masalah model/rantaian/token berulang kali. Ia bukan.
PROMPT memang ~30,721 token, dan punca terbesar ialah `skills.auto_load`:
konfigurasi itu memuat skill secara PENUH ke setiap mesej.

Diukur 11 Nov 2026 dengan 63 nama dalam auto_load:

    332,799 bait  ~83,199 token   <- kalau semuanya dijumpai dan dimuat
    120,918 bait  ~30,229 token   <- prompt sebenar dihantar (49 skill dimuat)

Pengajaran: setiap 4 bait ≈ 1 token. Siling 32,768 bermakna prompt + output
mesti < 32,768. Output lalai 2,048, jadi prompt mesti < ~30,700.

GUNA SEBELUM COMMIT apa-apa perubahan pada config.yaml atau skills/:

    python3 scripts/ukur_prompt.py <direktori-home>

Ia mencetak pecahan dan memberitahu sama ada selamat.
"""

from __future__ import annotations

import glob
import os
import sys

# Nisbah kasar. Inggeris ~4.0 bait/token, Melayu/teknikal sedikit lebih padat,
# jadi 3.8 lebih selamat (anggaran lebih tinggi = lebih awal amaran).
BAIT_PER_TOKEN = 3.8

# Siling sebenar model yang bot ini guna, dan output lalai yang diminta.
SILING = 32768
OUTPUT_WAKTU = 2048


def saiz(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def kumpul(home: str) -> dict:
    def ambil(*nama: str) -> int:
        return sum(saiz(os.path.join(home, n)) for n in nama)

    # auto_load: baca nama dari config, cari SKILL.md masing-masing.
    auto_bait = 0
    auto_senarai = []
    peta = {}
    for p in glob.glob(os.path.join(home, "skills", "**", "SKILL.md"), recursive=True):
        peta[os.path.basename(os.path.dirname(p))] = p

    cfg = os.path.join(home, "config.yaml")
    if os.path.exists(cfg):
        try:
            import yaml
            with open(cfg, encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            for n in (c.get("skills") or {}).get("auto_load") or []:
                p = peta.get(n)
                if p:
                    s = saiz(p)
                    auto_bait += s
                    auto_senarai.append((s, n))
        except Exception as e:
            print(f"AMARAN: config.yaml tidak boleh dibaca ({e})")

    # Indeks semua skill: nama + description sahaja, bukan kandungan.
    idx_bait = 0
    for p in peta.values():
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for baris in f:
                    if baris.startswith("description:"):
                        idx_bait += len(baris)
                        break
                    if baris.strip() == "---" and idx_bait:
                        break
        except OSError:
            pass

    return {
        "auto_bait": auto_bait,
        "auto_senarai": auto_senarai,
        "soal_bait": ambil("SOUL.md", "AGENTS.md",
                           os.path.join("memories", "MEMORY.md"),
                           os.path.join("memories", "USER.md")),
        "idx_bait": idx_bait,
        "bil_skill": len(peta),
    }


def main() -> int:
    home = sys.argv[1] if len(sys.argv) > 1 else "."
    d = kumpul(home)

    def tok(b: int) -> int:
        return int(b / BAIT_PER_TOKEN)

    auto, soal, idx = d["auto_bait"], d["soal_bait"], d["idx_bait"]
    jumlah = auto + soal + idx
    siling_prompt = SILING - OUTPUT_WAKTU

    print(f"UKUR PROMPT — {os.path.abspath(home)}")
    print(f"  {d['bil_skill']} skill dijumpai dalam skills/")
    print()
    print(f"  {'skill auto_load':<24}{auto:>9,} bait  ~{tok(auto):>6,} token")
    print(f"  {'SOUL+AGENTS+memori':<24}{soal:>9,} bait  ~{tok(soal):>6,} token")
    print(f"  {'index skill':<24}{idx:>9,} bait  ~{tok(idx):>6,} token")
    print("  " + "-" * 50)
    print(f"  {'JUMLAH PROMPT':<24}{jumlah:>9,} bait  ~{tok(jumlah):>6,} token")
    print()
    print(f"  siling model             {SILING:>9,} token")
    print(f"  output diminta           {OUTPUT_WAKTU:>9,} token")
    print(f"  prompt mesti bawah       {siling_prompt:>9,} token")
    baki = siling_prompt - tok(jumlah)
    print()

    if d["auto_senarai"]:
        print("  auto_load terbesar:")
        for s, n in sorted(d["auto_senarai"], reverse=True)[:6]:
            print(f"    {s:>7,} bait ~{tok(s):>5,} tok  {n}")
        print()

    if baki < 0:
        print(f"  HASIL: GAGAL — lebih {abs(baki):,} token. Mesej akan DITOLAK.")
        print("  Buang nama dari skills.auto_load (kandungan dimuat atas permintaan")
        print("  melalui skill_view, jadi tiada keupayaan hilang).")
        return 1
    if baki < 4096:
        print(f"  HASIL: RAPUH — baki {baki:,} token sahaja untuk mesej + sejarah.")
        print("  Satu perbualan panjang akan menolak keluar siling.")
        return 0
    print(f"  HASIL: SELAMAT — baki {baki:,} token untuk mesej + sejarah.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
