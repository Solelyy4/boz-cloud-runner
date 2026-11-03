#!/usr/bin/env bash
# ensure_cloud.sh — penjaga bot awan BOZ + pencetus auto-evolusi.
#
# Dijalankan oleh cron `ensure-cloud` setiap 15 minit (SATU-SATUNYA jadual yang GitHub
# benar-benar hormati pada repo ini — disahkan: `*/10` pada evolve.yml diabaikan sepenuhnya,
# manakala `*/15` pada ensure-cloud.yml dan `13 * * * *` pada telegram.yml berjalan).
#
# Kerja:
#  1. Ujian kesihatan Bot API (rekod ke telegram_api_health.log).
#  2. Cetus `evolve` (auto-evolusi skill/dialek) — di sini, bukan melalui cron sendiri,
#     kerana cron GitHub mengabaikan jadual */10 pada repo ini.
#  3. Pastikan SENTIASA ada satu gateway telegram-hermes hidup (mula baharu kalau tiada).
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

# --- 2. Auto-evolusi: cetus dari sini (cron */10 pada evolve.yml diabaikan GitHub) ---
EVO_AKTIF=$(gh run list --repo "$REPO" --workflow "evolve" --limit 10 \
  --json status --jq '[.[] | select(.status=="in_progress" or .status=="queued" or .status=="waiting")] | length')
if [ "${EVO_AKTIF:-0}" -eq 0 ]; then
  echo "mencetus evolve (auto-evolusi skill/dialek)"
  gh workflow run "evolve.yml" --repo "$REPO" >/dev/null 2>&1 || echo "cetus evolve gagal"
else
  echo "evolve sudah aktif ($EVO_AKTIF run) — langkau"
fi

if [ "${aktif:-0}" -gt 0 ]; then
  echo "ada $aktif run gateway aktif — tiada tindakan"
  exit 0
fi

echo "tiada run gateway aktif — memulakan gateway baharu"
gh workflow run "$WF" --repo "$REPO"
