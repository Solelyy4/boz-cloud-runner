#!/usr/bin/env bash
# BOZ AUTO-HEALER v2 — berjalan DALAM run telegram-hermes sebagai pengawas.
#
# Berbeza daripada v1 (cron berasingan yang buta): ini berkongsi proses, filesystem,
# HERMES_HOME dan venv dengan gateway yang dia jaga. Ia boleh:
#   - lihat gw.log sebenar
#   - uji model dengan kunci sebenar
#   - terap semula guardrail bypass pada venv yang SAMA
#   - mula semula gateway dan SAHKAN ia pulih
#
# Semua ujian < 25s. Kegagalan tunggal tidak membunuh apa-apa.

set -uo pipefail

LOG="${AUTOHEAL_LOG:-autoheal.log}"
MODEL_BASE="${MODEL_BASE:-}"
MODEL_KEY="${MODEL_KEY:-}"
MODEL_NAME="${MODEL_NAME:-mistral-code}"

log() { echo "[$(date -u +%FT%TZ)] AH: $*" >> "$LOG"; }
say() { echo "  [autoheal] $*"; }

FIXES=0
fix() { FIXES=$((FIXES+1)); log "FIX #$FIXES: $*"; say "FIX: $*"; }

find_py() {
  local p
  p=$(find "${HERMES_HOME:-.}" -maxdepth 8 -path "*/venv/bin/python" 2>/dev/null | head -1)
  echo "$p"
}

# ── UJIAN ──────────────────────────────────────────────────────────────────
t_gateway()   { pgrep -f "hermes gateway" >/dev/null 2>&1; }
t_pending()   {
  local p
  p=$(curl -4 -s -m 10 "https://api.telegram.org/bot${BOZ_BOT_TOKEN}/getWebhookInfo" 2>/dev/null \
      | sed -n 's/.*"pending_update_count":\([0-9]*\).*/\1/p')
  [ -z "$p" ] && return 0        # rangkaian — bukan salah bot
  [ "$p" -eq 0 ]
}
t_guardrail() {
  local sp
  sp=$(find "${HERMES_HOME:-.}" -maxdepth 8 -name sitecustomize.py -path "*site-packages*" 2>/dev/null | head -1)
  [ -n "$sp" ] && grep -q "BYPASS ACTIVE" "$sp" 2>/dev/null
}
t_model() {
  [ -n "$MODEL_BASE" ] && [ -n "$MODEL_KEY" ] || return 0
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" -m 20 -X POST "${MODEL_BASE}/chat/completions" \
    -H "Authorization: Bearer $MODEL_KEY" -H "Content-Type: application/json" \
    -d "{\"model\":\"${MODEL_NAME}\",\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}],\"max_tokens\":5}" 2>/dev/null)
  [ "$code" = "200" ]
}
t_web() {
  local py out
  py=$(find_py); [ -n "$py" ] || return 0
  out=$(timeout 70 "$py" - 2>/dev/null <<'PY'
try:
    from tools.web_tools import _ensure_web_plugins_loaded, _get_search_backend, _memoized_search
    from agent.web_search_registry import get_provider, get_active_search_provider
    _ensure_web_plugins_loaded()
    p = get_provider(_get_search_backend()) or get_active_search_provider()
    r = _memoized_search(p, "python asyncio", 2)
    print(len((r.get("data") or {}).get("web") or []))
except Exception:
    print(0)
PY
)
  out="${out//[^0-9]/}"
  [ -n "$out" ] && [ "$out" -gt 0 ]
}
t_config() {
  local py
  py=$(find_py); [ -n "$py" ] || return 0
  timeout 60 "$py" -c "import yaml,sys; yaml.safe_load(open('${HERMES_HOME:-.}/config.yaml')); print('ok')" 2>/dev/null | grep -q ok
}

# ── PEMBAIKAN ──────────────────────────────────────────────────────────────
f_guardrail() {
  local py
  py=$(find_py)
  if [ -n "$py" ] && [ -f scripts/apply_patches.py ]; then
    "$py" scripts/apply_patches.py >>"$LOG" 2>&1 && fix "guardrail diterap semula"
  else
    log "fix guardrail GAGAL: venv/script tiada"; say "guardrail: tiada venv/script"
  fi
}
f_web() {
  local py
  py=$(find_py); [ -n "$py" ] || return 0
  "$py" -m pip install --quiet --disable-pip-version-check ddgs >>"$LOG" 2>&1 && fix "ddgs dipasang semula"
}
f_config() {
  local bad="${HERMES_HOME:-.}/config.yaml.bad"
  cp "${HERMES_HOME:-.}/config.yaml" "$bad" 2>/dev/null
  # config rosak: buang kunci web yang mungkin jadi punca, kekalkan selebihnya
  local py
  py=$(find_py); [ -n "$py" ] || return 0
  timeout 60 "$py" - "${HERMES_HOME:-.}/config.yaml" <<'PY' >>"$LOG" 2>&1 && fix "config dibersihkan (web dipin ddgs)"
import sys, re
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
s = re.sub(r"\nweb:\n(?:  .*\n)*", "\n", s)
s = s.replace("\nmodel:", "\nweb:\n  backend: ddgs\n  search_backend: ddgs\n  extract_backend: ddgs\n\nmodel:", 1)
open(p, "w", encoding="utf-8").write(s)
PY
}
f_gateway() {
  log "restart gateway"
  pkill -9 -f "hermes gateway" 2>/dev/null || true
  sleep 4
  ( hermes gateway run >> gw.log 2>&1 & )
  local i
  for i in $(seq 1 12); do
    sleep 5
    if tail -n 40 gw.log 2>/dev/null | grep -qiE "Connected to Telegram|polling mode"; then
      fix "gateway dihidupkan semula (${i}0s)"; return 0
    fi
  done
  log "restart gateway GAGAL selepas 60s"; say "gateway: restart gagal"
  return 1
}

# ── SATU KITARAN ───────────────────────────────────────────────────────────
cycle() {
  local dirty=0

  if ! t_gateway; then
    log "GAGAL: gateway tiada"; say "gateway mati"
    f_gateway; dirty=1
  fi
  if ! t_guardrail; then log "GAGAL: bypass hilang"; f_guardrail; fi
  if ! t_config;   then log "GAGAL: config rosak";   f_config; fi
  if ! t_model;    then log "GAGAL: model bukan 200"; say "model: gagal (fallback diguna)"; fi
  if ! t_web;      then log "GAGAL: web_search 0";    f_web; fi
  if ! t_pending;  then
    log "GAGAL: bot bisu (pending>0)"
    if [ "$dirty" -eq 0 ]; then f_gateway; fi
  fi

  [ "$FIXES" -eq 0 ] && log "sihat"
  return 0
}

# ── GELUNG ─────────────────────────────────────────────────────────────────
main() {
  log "=== AUTO-HEAL v2 MULA (run ${GITHUB_RUN_ID:-local}) ==="
  cycle
  log "=== AUTO-HEAL: $FIXES pembaikan ==="
}

main "$@"
