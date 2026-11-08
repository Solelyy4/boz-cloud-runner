#!/usr/bin/env bash
# gateway_jalan.sh — jalankan gateway Hermes dengan pengawasan berasas bukti.
#
# REKA BENTUK BERSIH (8 Nov 2026). Setiap keputusan menjawab kegagalan yang DISAHKAN.
#
# PRINSIP:
#   1. Satu proses gateway sahaja. Tiada getUpdates dari skrip ini. Pernah berlaku:
#      getUpdates dalam workflow merampas long-poll -> 409 -> adapter PARKED -> bot bisu.
#   2. Watchdog TIDAK membunuh bot yang sihat. Pernah berlaku: bot dibunuh setiap
#      ~12 minit kerana `pending=0` disalah anggap sebagai "tersekat". pending=0
#      adalah NORMAL bila tiada mesej.
#   3. Bunuh gateway guna PID yang dijejak. `pgrep -f` pernah memadankan skrip ini
#      sendiri -> bunuh diri -> rc=127 setiap kali.
#   4. Berlalu masa, bukan selama-lamanya: MASA_JALAN minit, kemudian keluar BERSIH
#      supaya run berikutnya (schedule) mula tanpa pertindihan.
#   5. Peronda melaporkan keadaan rangkaian SEBENAR dari runner ini, dan beritahu BOZ
#      secara jujur bila Telegram tidak dapat dihubungi.
set -uo pipefail

: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN kosong}"
: "${MISTRAL_API_KEY:?MISTRAL_API_KEY kosong}"
MASA_JALAN="${MASA_JALAN:-720}"
GW_LOG="gw.log"
TRACE_LOG="gw_trace.log"

export HERMES_HOME="${HERMES_HOME:-$PWD/home}"
export PATH="$HOME/.local/bin:$PATH"

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$GW_LOG"; }

: > "$GW_LOG"
: > "$TRACE_LOG"
log "=== gateway_jalan mula: run=${GITHUB_RUN_ID:-lokal} masa_jalan=${MASA_JALAN}m ==="

# ---------- cari venv Hermes ----------
GWPY=""
for cand in "$HERMES_HOME"/installs/*/environments/*/venv/bin/python; do
  [ -x "$cand" ] || continue
  if "$cand" -c "import hermes_cli" 2>/dev/null; then GWPY="$cand"; break; fi
done
if [ -z "$GWPY" ]; then
  log "FATAL: venv Hermes tidak dijumpai — gateway tidak boleh mula"
  exit 1
fi
log "gateway python: $GWPY"

# ---------- jejak mesej masuk (bukti bot MEMPROSES, bukan sekadar bersambung) ----------
# Adapter mencatat mesej pada aras debug; gateway guna WARNING, jadi pemprosesan
# berlaku tetapi kita BUTA. jejak_bot.py menulis [JEJAK] pada aras WARNING.
# Salinan workspace dicipta SEMASA boot, jadi tampal awal + pemanjat latar.
if [ -f scripts/jejak_bot.py ]; then
  HERMES_HOME="$HERMES_HOME" "$GWPY" scripts/jejak_bot.py 2>&1 | grep -E '^JEJAK|^  \[' | tee -a "$GW_LOG" || true
  (
    for _ in $(seq 1 30); do
      sleep 15
      ada=0
      for d in "$HERMES_HOME"/installs/*/environments/*/workspace; do
        [ -f "$d/plugins/platforms/telegram/adapter.py" ] && ada=1
      done
      [ "$ada" = "1" ] || continue
      HERMES_HOME="$HERMES_HOME" "$GWPY" scripts/jejak_bot.py >/dev/null 2>&1 || true
      echo "jejak-pemanjat: salinan workspace ditampal" >> "$GW_LOG"
      break
    done
  ) &
fi

# ---------- peronda latar: keadaan rangkaian sebenar, tanpa getUpdates ----------
(
  python3 scripts/peronda_telegram.py \
    --tunggu 120 --pusingan 0 --keluaran status_peronda.jsonl \
    --beritahu-selepas 3 >> "$GW_LOG" 2>&1
) &
PERONDA_PID=$!
log "peronda latar dipasang (pid=$PERONDA_PID, denyut 120s)"

# ---------- penjejak: push log setiap 90s supaya operator nampak keadaan ----------
(
  while true; do
    sleep 90
    [ -s "$GW_LOG" ] || continue
    { echo "=== TRACE $(date -u +%FT%TZ) run ${GITHUB_RUN_ID:-lokal} ==="; tail -n 250 "$GW_LOG"; } > "$TRACE_LOG.tmp"
    mv "$TRACE_LOG.tmp" "$TRACE_LOG"
    git fetch origin master -q >/dev/null 2>&1 || true
    git checkout -q -B trace-tmp origin/master >/dev/null 2>&1 || true
    cp "$TRACE_LOG" gw_trace.log
    git add -f gw_trace.log >/dev/null 2>&1
    git -c user.email=bot@local -c user.name=bot commit -qm "trace $(date -u +%FT%TZ)" >/dev/null 2>&1 || true
    git push origin HEAD:master >/dev/null 2>&1 || true
  done
) &
TRACE_PID=$!

# ---------- pengesan kematian gateway ----------
gateway_hidup() { kill -0 "$1" 2>/dev/null; }

bunuh_gateway() {
  # Hanya PID yang kita kenal. JANGAN pgrep -f: ia memadankan skrip ini sendiri
  # (baris arahan mengandungi "hermes_cli.main"), menyebabkan bot membunuh dirinya.
  local pid="${1:-}"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && kill -TERM "$pid" 2>/dev/null
  sleep 5
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
  return 0
}

# ---------- denyut: adakah Telegram boleh dicapai dari sini SEKARANG? ----------
telegram_hidup() {
  local code
  code=$(curl -4 -s -o /dev/null -m 15 -w "%{http_code}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" || echo 000)
  [ "$code" = "200" ]
}

MULA=$(date +%s)
HAD_SAAT=$(( MASA_JALAN * 60 ))
cubaan=0

while true; do
  cubaan=$(( cubaan + 1 ))
  lalu=$(date +%s)
  baki=$(( HAD_SAAT - (lalu - MULA) ))
  if [ "$baki" -le 120 ]; then
    log "masa jalan hampir tamat (baki ${baki}s) — berhenti BERSIH"
    break
  fi

  MARK=$(wc -l < "$GW_LOG" 2>/dev/null || echo 0)
  log "--- cubaan $cubaan: mula gateway ---"

  # LONG-POLL TUNGGAL. Tiada proses lain menyentuh getUpdates.
  PYTHONUNBUFFERED=1 "$GWPY" -c \
    "import sys; from hermes_cli.main import main; sys.argv=['hermes','gateway','run']; main()" \
    >> "$GW_LOG" 2>&1 &
  GW_PID=$!
  log "gateway pid=$GW_PID"

  # Tunggu tanda sambungan (maks 180s). Tanda mesti datang SELEPAS penanda MARK.
  TUNGGU=0
  SAMBUNG=0
  for _ in $(seq 1 36); do
    sleep 5
    TUNGGU=$(( TUNGGU + 5 ))
    if tail -n +$(( MARK + 1 )) "$GW_LOG" | grep -q "Connected to Telegram"; then
      SAMBUNG=1
      break
    fi
    gateway_hidup "$GW_PID" || break
  done

  if [ "$SAMBUNG" = "1" ]; then
    log "SAMBUNG OK selepas ${TUNGGU}s (bukti: baris 'Connected to Telegram')"
  else
    log "TIDAK SAMBUNG selepas ${TUNGGU}s — semak rangkaian/ralat di atas"
  fi

  # ---------- gelung pengawasan ----------
  tick=0
  while gateway_hidup "$GW_PID"; do
    sleep 60
    tick=$(( tick + 1 ))

    # (a) proses mati?
    if ! gateway_hidup "$GW_PID"; then break; fi

    # (b) ralat fatal adapter?
    if tail -n +$(( MARK + 1 )) "$GW_LOG" | grep -q "Fatal telegram adapter error"; then
      log "ralat fatal adapter dikesan -> mula semula"
      bunuh_gateway "$GW_PID"
      break
    fi

    # (c) masa jalan tamat?
    if [ $(( $(date +%s) - MULA )) -ge $HAD_SAAT ]; then
      log "masa jalan tamat -> hentikan gateway BERSIH"
      bunuh_gateway "$GW_PID"
      break
    fi

    # (d) watchdog: proses HIDUP tetapi tiada aktiviti log DAN Telegram tak tercapai.
    #     Ini berbeza daripada "pending=0 kerana tiada mesej" — itu NORMAL dan TIDAK
    #     membunuh bot. Kita hanya bertindak bila ADA bukti sambungan rosak.
    if [ $(( tick % 10 )) -eq 0 ]; then
      BARU=$(wc -l < "$GW_LOG" 2>/dev/null || echo 0)
      if [ "$BARU" -eq "$MARK" ] && [ "$SAMBUNG" = "1" ] && ! telegram_hidup; then
        log "watchdog: log beku + Telegram tidak menjawab -> sambungan rosak, mula semula"
        bunuh_gateway "$GW_PID"
        break
      fi
    fi

    # (e) pantau fd — kebocoran descriptor memberi ConnectError('') kosong.
    if [ -d "/proc/$GW_PID/fd" ]; then
      FD=$(ls /proc/"$GW_PID"/fd 2>/dev/null | wc -l)
      if [ "$FD" -gt 700 ]; then
        log "KEBOCORAN FD: $FD — bersara proses untuk pulih"
        bunuh_gateway "$GW_PID"
        break
      fi
    fi

    # (f) denyut setiap 10 minit
    if [ $(( tick % 10 )) -eq 0 ]; then
      log "denyut tick=$tick pid=$GW_PID"
    fi
  done

  wait "$GW_PID" 2>/dev/null
  RC=$?
  log "=== cubaan $cubaan tamat: rc=$RC ==="

  # Jeda sebelum cubaan berikut, melainkan masa jalan sudah tamat.
  if [ $(( $(date +%s) - MULA )) -ge $HAD_SAAT ]; then break; fi
  JEDA=$(( cubaan * 20 )); [ "$JEDA" -gt 300 ] && JEDA=300
  log "jeda ${JEDA}s sebelum cubaan berikut"
  sleep "$JEDA"
done

# ---------- penutup: hentikan latar, simpan log ----------
kill "$TRACE_PID" "$PERONDA_PID" 2>/dev/null || true
cp "$GW_LOG" /tmp/gw_akhir.log 2>/dev/null || true
log "=== gateway_jalan tamat: ${cubaan} cubaan, $(( ($(date +%s) - MULA) / 60 )) minit ==="
tail -n 40 "$GW_LOG"
