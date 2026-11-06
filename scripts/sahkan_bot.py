#!/usr/bin/env python3
"""Sahkan bot Telegram menjawab. Dipanggil dari workflow uji-bot.yml.

Kenapa berasingan: skrip sebaris dalam YAML rapuh (petikan bertindih) dan menyukarkan
debug. Fail berasingan boleh diuji tempatan.

Guna:
  python3 sahkan_bot.py <jawapan.txt> <message_id>
Keluaran baris tunggal untuk workflow.
"""
from __future__ import annotations

import json
import sys

GELUNG = ("tunggu sebentar", "saya cari lagi", "sila tunggu")


def main() -> int:
    if len(sys.argv) < 3:
        print("guna: sahkan_bot.py <jawapan.txt> <message_id>")
        return 2
    jalan, mid = sys.argv[1], sys.argv[2]
    teks = ""
    try:
        teks = open(jalan, encoding="utf-8").read()
    except FileNotFoundError:
        pass
    teks = teks.strip()
    if not teks:
        print("HASIL: TIADA_JAWAPAN")
        return 0
    print(f"HASIL: JAWAB ({len(teks)} aksara)")
    rendah = teks.lower()
    if any(g in rendah for g in GELUNG):
        print("AMARAN: jawapan mengandungi ayat gelung ('tunggu sebentar' dll)")
    if teks.startswith("SIAP:") or "MEDIA:" in teks or teks.startswith("->"):
        print("FORMAT: ikut SIAP/hasil")
    else:
        print("FORMAT: bebas")
    print("JAWAPAN_MULA")
    print(teks[:1200])
    print("JAWAPAN_TAMAT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
