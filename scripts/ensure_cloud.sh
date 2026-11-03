#!/usr/bin/env bash
# ensure_cloud.sh — pastikan bot Hermes awan SENTIASA ada satu gateway hidup.
# Dipasang di dalam repo-runner sendiri; dijalankan oleh cron GH Actions setiap 15 minit.
# Kalau ada run telegram-hermes aktif (in_progress atau queued), keluar senyap.
# Kalau tiada, mula satu run baharu -> celah antara sesi jadi ~0 saat.
set -euo pipefail
REPO="Solelyy4/boz-cloud-runner"
WF="telegram-hermes"

# --- Ujian kesihatan Bot API: rekod keadaan supaya kita tahu bila Telegram pulih ---
STATE="telegram_api_health.log"
TOK="${TELEGRAM_BOT_TOKEN:-}"
if [ -n "$TOK" ]; then
  CODE=$(curl -s -o /dev/null -m 20 -w "%{http_code}" "https://api.telegram.org/bot${TOK}/getMe" || echo "000")
  echo "$(date -u +%FT%TZ) health HTTP=$CODE" >> "$STATE"
  tail -n 200 "$STATE" > "${STATE}.tmp" && mv "${STATE}.tmp" "$STATE"
  echo "Bot API health: HTTP $CODE"
  git add "$STATE" >/dev/null 2>&1 || true
  git -c user.email=bot@local -c user.name=bot commit -qm "health $CODE $(date -u +%FT%TZ)" >/dev/null 2>&1 || true
  git push origin HEAD:master >/dev/null 2>&1 || true
fi

aktif=$(gh run list --repo "$REPO" --workflow "$WF" --limit 10 \
        --json status --jq '[.[] | select(.status=="in_progress" or .status=="queued" or .status=="waiting")] | length')

if [ "${aktif:-0}" -gt 0 ]; then
  echo "ada $aktif run aktif — tiada tindakan"
  exit 0
fi

echo "tiada run aktif — memulakan gateway baharu"
gh workflow run "$WF" --repo "$REPO"
