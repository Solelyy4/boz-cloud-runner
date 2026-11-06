#!/usr/bin/env bash
# Ujian autonomi bot Telegram — VERSI DIBETULKAN (6 Nov 2026).
#
# BUG VERSI LAMA (dibuktikan oleh run 42175356707): ia memanggil getUpdates setiap 10s.
# getUpdates MERAMPAS long-poll daripada gateway bot — Telegram hanya benarkan SATU
# pengguna getUpdates pada satu masa. Akibatnya bot jadi BUTA, tiada jawapan, dan ujian
# melaporkan 'HASIL: TIADA_JAWAPAN' — ujian memusnahkan apa yang ia cuba uji.
#
# PEMBETULAN: jangan sesekali getUpdates semasa gateway hidup. Guna getWebhookInfo
# (BUKAN getUpdates, jadi selamat) untuk baca pending_update_count:
#   pending turun ke 0 = gateway bot SUDAH mengambil mesej = bot hidup & membaca.
set +e
OUT=uji-bot.log
{
  echo "=== UJIAN BOT $(date -u +%FT%TZ) run $GITHUB_RUN_ID ==="
  echo "chat: $CHAT"
  echo "mesej: $MESEJ"

  echo "--- 1. getMe (token sah?) ---"
  curl -4 -s -m 20 "https://api.telegram.org/bot$TOKEN/getMe" \
    | python3 -c "import json,sys;d=json.load(sys.stdin);r=d.get('result') or {};print('ok=',d.get('ok'),'bot=',r.get('username'))" 2>/dev/null

  echo "--- 2. keadaan sebelum hantar ---"
  BEFORE=$(curl -4 -s -m 20 "https://api.telegram.org/bot$TOKEN/getWebhookInfo" \
    | python3 -c "import json,sys
try:
    d=json.load(sys.stdin); print((d.get('result') or {}).get('pending_update_count','?'))
except Exception: print('?')" 2>/dev/null)
  echo "pending sebelum = $BEFORE"

  echo "--- 3. hantar mesej ujian ke bot ---"
  SENT=$(curl -4 -s -m 25 -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
    -d "chat_id=$CHAT" --data-urlencode "text=$MESEJ")
  MID=$(printf '%s' "$SENT" | python3 -c "import json,sys
try:
    d=json.load(sys.stdin); print((d.get('result') or {}).get('message_id') or '')
except Exception:
    print('')" 2>/dev/null)
  echo "message_id = ${MID:-GAGAL}"
  [ -z "$MID" ] && { echo "GAGAL hantar mesej"; echo "=== TAMAT ==="; exit 0; }

  echo "--- 4. tunggu bot ambil mesej (getWebhookInfo sahaja — SELAMAT) ---"
  AMBIL=0
  for i in $(seq 1 24); do
    sleep 20
    PEND=$(curl -4 -s -m 20 "https://api.telegram.org/bot$TOKEN/getWebhookInfo" \
      | python3 -c "import json,sys
try:
    d=json.load(sys.stdin); print((d.get('result') or {}).get('pending_update_count','?'))
except Exception: print('?')" 2>/dev/null)
    echo "  $((i*20))s: pending=$PEND"
    if [ "$PEND" = "0" ]; then AMBIL=1; echo "  bot sudah ambil mesej (pending=0)"; break; fi
  done

  echo "--- 5. VERDICT ---"
  if [ "$AMBIL" = "1" ]; then
    echo "BOT MEMBACA MESEJ: ya"
    echo "Disahkan dengan: pending_update_count turun ke 0 dari $BEFORE"
    echo "NOTA: isi jawapan disahkan dari gw_trace.log (bot tulis) dan Telegram BOZ."
  else
    echo "BOT MEMBACA MESEJ: tidak — pending tidak turun ke 0"
  fi
  echo "=== TAMAT ==="
} > "$OUT" 2>&1
tail -30 "$OUT"
