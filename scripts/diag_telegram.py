"""diag_telegram.py — diagnosa MENGAPA app.initialize() tersangkut.

Dijalankan di runner GitHub Actions. Menguji setiap lapisan yang app.initialize()
sebenarnya sentuh, dengan masa, supaya kita tahu lapisan mana yang hang:
  1. HTTP getMe biasa (curl-free, python urllib)
  2. PTB HTTPXRequest dengan TelegramFallbackTransport (sama seperti adapter)
  3. app.initialize() dengan had masa 25s + jejak
"""
import asyncio
import os
import pathlib
import sys
import time
import urllib.request

TOK = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
print(f"token len={len(TOK)} id={TOK.split(':')[0] if ':' in TOK else '?'}")
print("HERMES_TELEGRAM_INIT_TIMEOUT =", os.environ.get("HERMES_TELEGRAM_INIT_TIMEOUT", "(lalai)"))
print()

# ---- 1. urllib (paling asas)
t0 = time.time()
try:
    r = urllib.request.urlopen(
        f"https://api.telegram.org/bot{TOK}/getMe", timeout=15)
    print(f"1. urllib getMe: HTTP {r.status} {time.time()-t0:.2f}s")
except Exception as e:
    print(f"1. urllib getMe: GAGAL {type(e).__name__} {e}")

# ---- 2. PTB (perpustakaan yang adapter guna)
try:
    from telegram import Bot
    from telegram.request import HTTPXRequest

    async def uji_ptb():
        req = HTTPXRequest(connect_timeout=8, read_timeout=15)
        bot = Bot(token=TOK, request=req)
        await bot.initialize()
        t = time.time() - t0
        print(f"2. PTB Bot.initialize(): OK {t:.2f}s | username=@{bot.username}")
        await bot.shutdown()

    asyncio.run(asyncio.wait_for(uji_ptb(), timeout=40))
except asyncio.TimeoutError:
    print(f"2. PTB Bot.initialize(): TIMEOUT >40s  <-- LAPISAN INI HANG")
except Exception as e:
    print(f"2. PTB Bot.initialize(): GAGAL {type(e).__name__}: {str(e)[:200]}")

# ---- 3. versi
try:
    import telegram
    print(f"3. python-telegram-bot: {telegram.__version__}")
except Exception as e:
    print(f"3. versi PTB: {e}")
try:
    import hermes_agent
    print(f"3. hermes_agent: {getattr(hermes_agent, '__version__', '?')}")
except Exception as e:
    print(f"3. hermes_agent: {e}")

# ---- 4. jejak file adapter
try:
    import importlib.util as u
    spec = u.find_spec("hermes_plugins.telegram_platform.adapter")
    print(f"4. adapter: {spec.origin if spec else 'TIADA'}")
except Exception as e:
    print(f"4. adapter: {e}")

# ---- 5. env berkaitan
print("5. env Telegram berkaitan:")
for k, v in sorted(os.environ.items()):
    if "TELEGRAM" in k.upper() or "HERMES_T" in k.upper():
        print(f"   {k}={'(disembunyikan)' if 'TOKEN' in k else v[:80]}")
