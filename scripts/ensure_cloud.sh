#!/usr/bin/env bash
# ensure_cloud.sh — pastikan bot Hermes awan SENTIASA ada satu gateway hidup.
# Dipasang di dalam repo-runner sendiri; dijalankan oleh cron GH Actions setiap 15 minit.
# Kalau ada run telegram-hermes aktif (in_progress atau queued), keluar senyap.
# Kalau tiada, mula satu run baharu -> celah antara sesi jadi ~0 saat.
set -euo pipefail
REPO="Solelyy4/boz-cloud-runner"
WF="telegram-hermes"

aktif=$(gh run list --repo "$REPO" --workflow "$WF" --limit 10 \
        --json status --jq '[.[] | select(.status=="in_progress" or .status=="queued" or .status=="waiting")] | length')

if [ "${aktif:-0}" -gt 0 ]; then
  echo "ada $aktif run aktif — tiada tindakan"
  exit 0
fi

echo "tiada run aktif — memulakan gateway baharu"
gh workflow run "$WF" --repo "$REPO"
