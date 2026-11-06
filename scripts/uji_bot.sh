#!/usr/bin/env bash
# Ujian autonomi bot Telegram: hantar soalan sebenar, tunggu jawapan, sahkan.
# Dipanggil dari .github/workflows/uji-bot.yml. Guna API awam sahaja.
#
# PENTING: getUpdates hanya boleh dipegang SATU proses. Bot gateway Hermes sedang
# long-poll, jadi getUpdates kita mungkin pulang 409 atau kosong. Untuk ujian ini kita
# hantar sahaja dan baca jawapan melalui getUpdates sementara gateway berehat sekejap
# (gateway akan pulih sendiri — ia tahan 409).
set +e
OUT=uji-bot.log
{
  echo "=== UJIAN BOT $(date -u +%FT%TZ) run $GITHUB_RUN_ID ==="
  echo "chat: $CHAT"
  echo "mesej: $MESEJ"

  echo "--- 1. getMe (token sah?) ---"
  curl -4 -s -m 20 "https://api.telegram.org/bot$TOKEN/getMe" | head -c 300
  echo

  echo "--- 2. hantar mesej ujian ke bot ---"
  SENT=$(curl -4 -s -m 25 -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
    -d "chat_id=$CHAT" --data-urlencode "text=$MESEJ")
  echo "$SENT" | head -c 300
  echo
  MID=$(printf '%s' "$SENT" | python3 -c "import json,sys
try:
    d=json.load(sys.stdin); print((d.get('result') or {}).get('message_id') or '')
except Exception:
    print('')" 2>/dev/null)
  echo "message_id = ${MID:-GAGAL}"

  echo "--- 3. tunggu jawapan bot (sehingga 8 minit) ---"
  : > jawapan.txt
  for i in $(seq 1 48); do
    sleep 10
    # timeout=0 supaya tidak menahan long-poll gateway lama
    curl -4 -s -m 30 "https://api.telegram.org/bot$TOKEN/getUpdates?timeout=0&limit=30" \
      | python3 -c "import json,sys
mid='$MID'
try:
    d=json.load(sys.stdin)
except Exception:
    raise SystemExit
for u in (d.get('result') or []):
    m=u.get('message') or u.get('edited_message') or {}
    if str(m.get('message_id'))!=mid and m.get('text'):
        open('jawapan.txt','w',encoding='utf-8').write(m['text'])
        break" 2>/dev/null
    if [ -s jawapan.txt ]; then
      echo "jawapan diterima pada cubaan $i ($((i*10))s)"
      break
    fi
    [ $((i % 6)) -eq 0 ] && echo "  ...tunggu $((i*10))s"
  done

  echo "--- 4. VERDICT ---"
  python3 scripts/sahkan_bot.py jawapan.txt "${MID:-0}"
  echo "=== TAMAT ==="
} > "$OUT" 2>&1
tail -40 "$OUT"
