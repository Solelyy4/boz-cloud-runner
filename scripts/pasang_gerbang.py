#!/usr/bin/env python3
"""pasang_gerbang.py — tanam GERBANG BALASAN terus ke dalam adapter Telegram Hermes.

MENGAPA PATCH TEKS (bukan plugin)
=================================
`send()` dalam `plugins/platforms/telegram/adapter.py` ialah SATU-SATUNYA pintu
untuk setiap mesej keluar (teks, chunk, rich). Membalut `Bot.send_message` (PTB)
TIDAK menangkap laluan rich/draft. Jadi kita tanam penapis DI DALAM `send()`.

PATCH YANG DITANAM (idempotent — corak sama, jangan tanam dua kali):
    async def send(self, chat_id, content, reply_to=None, metadata=None):
        [docstring "Send a message to a Telegram chat."]
+       content = _boz_gerbang(chat_id, content)      # gerbang BOZ
        if not self._bot:

`_boz_gerbang` diimport dari `scripts/balas_pantas.py` (diletak sebelah fail ini
oleh workflow). Kalau import gagal, fungsi pulang teks ASAL — bot tidak pernah
pecah kerana gerbang hilang; ia hanya kehilangan penapis.

Guna:
  python scripts/pasang_gerbang.py --adapter <laluan adapter.py> [--uji]
  python scripts/pasang_gerbang.py --cari        # cari adapter dalam HERMES_HOME
"""
from __future__ import annotations

import argparse
import glob
import io
import os
import re
import sys

CORAK_LAMA = (
    '        """Send a message to a Telegram chat."""\n'
    '        if not self._bot:'
)

CORAK_BAHARU = (
    '        """Send a message to a Telegram chat."""\n'
    '        # --- GERBANG BOZ (dipasang pasang_gerbang.py) ---\n'
    '        # BOZ: bot memuntahkan pautan + tutorial walaupun hanya dihantar "hi".\n'
    '        # Penapis jenis-mesej di sini memotongnya SEBELUM sampai ke Telegram.\n'
    '        # Import selamat: kalau modul tiada, teks asal dihantar (bot tidak pecah).\n'
    '        try:\n'
    '            from _boz_gerbang import tapis_keluar as _boz_tapis\n'
    '            content = _boz_tapis(chat_id, content)\n'
    '        except Exception:\n'
    '            pass\n'
    '        # --- TAMAT GERBANG BOZ ---\n'
    '        if not self._bot:'
)

CORAK_MASUK_LAMA = (
    '    async def handle_message(self, event: MessageEvent) -> None:\n'
    '        self._accept_update()'
)

CORAK_MASUK_BAHARU = (
    '    async def handle_message(self, event: MessageEvent) -> None:\n'
    '        # --- GERBANG BOZ: rekod mesej MASUK supaya penapis tahu jenis balasan ---\n'
    '        try:\n'
    '            from _boz_gerbang import set_masuk as _boz_masuk\n'
    '            _t = getattr(event, "text", None) or getattr(event, "content", None) or ""\n'
    '            _boz_masuk(_t if isinstance(_t, str) else str(_t))\n'
    '        except Exception:\n'
    '            pass\n'
    '        # --- TAMAT GERBANG BOZ ---\n'
    '        self._accept_update()'
)

PENANDA = "_boz_tapis(chat_id, content)"
PENANDA_MASUK = "_boz_masuk(_t if isinstance(_t, str) else str(_t))"


def cari_adapter(home: str) -> list[str]:
    pola = [
        os.path.join(home, "hermes-agent", "plugins", "platforms", "telegram", "adapter.py"),
        os.path.join(home, "**", "plugins", "platforms", "telegram", "adapter.py"),
    ]
    found: list[str] = []
    for p in pola:
        for f in glob.glob(p, recursive=True):
            if os.path.isfile(f) and f not in found:
                found.append(f)
    return found


def tanam(path: str) -> str:
    txt = io.open(path, encoding="utf-8").read()
    asal = txt
    status: list[str] = []

    # (1) penapis mesej keluar
    if PENANDA in txt:
        status.append("KELUAR=SUDAH")
    elif CORAK_LAMA in txt:
        txt = txt.replace(CORAK_LAMA, CORAK_BAHARU, 1)
        status.append("KELUAR=DITANAM")
    else:
        status.append("KELUAR=CORAK_TIDAK_PADAN")

    # (2) perakam mesej masuk
    if PENANDA_MASUK in txt:
        status.append("MASUK=SUDAH")
    elif CORAK_MASUK_LAMA in txt:
        txt = txt.replace(CORAK_MASUK_LAMA, CORAK_MASUK_BAHARU, 1)
        status.append("MASUK=DITANAM")
    else:
        status.append("MASUK=CORAK_TIDAK_PADAN")

    if txt != asal:
        # sahkan sintaks SEBELUM tulis (jangan rosakkan adapter bot)
        import ast
        try:
            ast.parse(txt)
        except SyntaxError as e:
            return f"GAGAL AST: {e}"
        io.open(path, "w", encoding="utf-8", newline="").write(txt)
    return " ".join(status)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="")
    ap.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", ""))
    a = ap.parse_args()

    sasaran = [a.adapter] if a.adapter else cari_adapter(a.hermes_home or ".")
    if not sasaran:
        print("TIDAK DIPASANG: adapter.py Telegram tidak dijumpai")
        return 2

    kod = 0
    for p in sasaran:
        hasil = tanam(p)
        print(f"  {p}\n    -> {hasil}")
        if "TIDAK_PADAN" in hasil or "GAGAL" in hasil:
            kod = 1
            txt = io.open(p, encoding="utf-8").read()
            m = re.search(r"    async def send\(\n.{0,200}?\"\"\"Send a message", txt, re.S)
            if m:
                print("    corak send() sebenar:")
                for ln in m.group(0).splitlines()[:6]:
                    print("      " + ln)
            m2 = re.search(r"    async def handle_message\(.*?\n\s+self\._accept_update\(\)", txt, re.S)
            if m2:
                print("    corak handle_message() sebenar:")
                for ln in m2.group(0).splitlines()[:4]:
                    print("      " + ln)
        elif "DITANAM" in hasil:
            print("    AST OK — adapter masih sah")
    return kod


if __name__ == "__main__":
    raise SystemExit(main())
