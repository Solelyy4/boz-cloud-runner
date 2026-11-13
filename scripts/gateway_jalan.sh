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

# ---------- jejak PTB process_update: titik masuk PALING AWAL ----------
# PEPIJAT: menampal adapter `_handle_text_message` tidak mencukupi. PTB mendaftar
# rujukan handler SEMASA `_register_handlers`, dan dispatch berlaku melalui
# `Application.process_update`. Menampal method adapter selepas pendaftaran tidak
# menjamin ia dipanggil (dan penjejak yang "dipasang" boleh kekal senyap).
#
# `Application.process_update` ialah pintu masuk SETIAP update sebelum sebarang
# penapis/auth/dispatch. Menampal di situ membuktikan sama ada Telegram benar-benar
# MENYERAHKAN mesej kepada proses ini — perbezaan antara "gateway mati" dan
# "handler tidak dipanggil". Ia juga menampal ke SALINAN PTB dalam venv, jadi ia
# berkuat kuasa walaupun workspace disalin semula.
if [ -f scripts/jejak_masuk.py ]; then
  HERMES_HOME="$HERMES_HOME" "$GWPY" scripts/jejak_masuk.py 2>&1 | tee -a "$GW_LOG" || \
    echo "AMARAN: jejak_masuk gagal (bukan ralat maut)" | tee -a "$GW_LOG"
fi

# ---------- JANGAN BUANG mesej BOZ semasa pulih konflik ----------
# Adapter memanggil `_start_polling_once(..., drop_pending_updates=True)` ketika
# memulihkan diri daripada konflik 409. Parameter itu MEMBUANG setiap update yang
# menunggu — iaitu mesej BOZ yang belum diproses. Kesannya: `pending` kekal 0,
# log berkata "Connected", `getMe` 200, tetapi TIADA mesej sampai selama-lamanya.
# Tukar kepada False: konflik masih diselesaikan tanpa mengorbankan mesej BOZ.
if [ -f scripts/jangan_buang.py ]; then
  HERMES_HOME="$HERMES_HOME" "$GWPY" scripts/jangan_buang.py 2>&1 | tee -a "$GW_LOG" || \
    echo "AMARAN: jangan_buang gagal (bukan ralat maut)" | tee -a "$GW_LOG"
fi

# ---------- NADI: jangan biar nod pengganti merampas token Telegram ----------
#
# PUNCA KONFLIK 409 YANG SEBENAR (dibuktikan 13 Nov 2026):
#   Repo Solelyy4/boz-lab-node menjalankan telekey/standby.sh — PENUNGGU yang
#   memerhati nadi di gist. Logiknya:
#       nadi muda (<180s)  -> nod senyap, PC yang poll Telegram
#       nadi basi (>180s)  -> nod AMBIL ALIH poll Telegram (telekey.py, token SAMA)
#   Nadi pada 16:56 UTC berumur 120,481 saat = 33.5 JAM, jadi nod percaya PC
#   sudah mati dan merampas token. Bot awan poll token yang sama -> 409.
#   ensure_cloud.sh (cron 15 minit) melihat gateway mati -> mula semula -> 409
#   lagi -> gelung abadi. Bot bisu sepenuhnya.
#
#   Tiada sesiapa menulis nadi itu sebelum ini — hanya pembaca yang wujud.
#   Kita jadi penulisnya: selagi gateway ini hidup, nadi dikemas kini, jadi nod
#   kekal senyap seperti yang direka.
(
  # VERSI 2 (13 Nov 2026): tulis melalui GIT PUSH, bukan REST API.
  #
  # Versi 1 menulis gist melalui REST API dan MATI dengan:
  #     NADI GAGAL: HTTP 403 Forbidden   (x4)
  #     gh api /rate_limit -> "API rate limit exceeded for user ID 330849825"
  # BOZ_PAT berkongsi had 5000/jam dengan workflow, ensure_cloud.sh (cron 15m),
  # penjejak trace (90s), dan peronda. Ia habis; nadi mati; nod rampas token;
  # bot awan 409; adapter PARKED; BOT BISU.
  #
  # Versi 2: tulis fail NADI dalam repo kerja -> git push (had berasingan) ->
  # raw.githubusercontent.com (CDN, tiada had API) -> nod baca < 180s -> senyap.
  # Gist kekal sebagai sandaran dalam skrip itu sendiri.
  "$GWPY" scripts/tulis_nadi.py --repo "$PWD" --loop 45 >> "$GW_LOG" 2>&1
) &
NADI_PID=$!
log "penulis nadi dipasang (pid=$NADI_PID, setiap 45s)"

# ---------- peronda latar: keadaan rangkaian sebenar, tanpa getUpdates ----------
(
  # Guna GWPY (venv Hermes), BUKAN python3 sistem. Di runner Ubuntu, python3 sistem
  # tiada modul yang peronda perlukan -> peronda mati senyap dan kita hilang bukti
  # rangkaian sebenar. Ini pernah menyembunyikan punca "Bad Gateway".
  "$GWPY" scripts/peronda_telegram.py \
    --tunggu 120 --pusingan 0 --keluaran status_peronda.jsonl \
    --beritahu-selepas 3 >> "$GW_LOG" 2>&1
) &
PERONDA_PID=$!

# ---------- peronda RANTAIAN: model mati semasa bot hidup ----------
# Gerbang menyemak model SEBELUM bot mula. Skrip ini menyemak SELEPAS itu — model
# boleh kena had atau provider boleh jatuh di tengah jalan. Tanpa ini, bot perlahan
# menjadi bisu tanpa sesiapa tahu.
(
  "$GWPY" scripts/jaga_rantaian.py "$HERMES_HOME/config.yaml" --loop 600 --beritahu \
    >> "$GW_LOG" 2>&1
) &
RANTAIAN_PID=$!
log "peronda rantaian dipasang (pid=$RANTAIAN_PID, semak setiap 10 min)"
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
    # Diari penampal juga dimuat naik: "PATCH OK" / "corak TIDAK padan" hanya wujud
    # di sini, dan tanpa fail ini kita buta bila penjejak gagal dipasang di runner.
    if [ -s scripts/jejak_masuk.log ]; then
      cp scripts/jejak_masuk.log jejak_masuk.log
      git add -f jejak_masuk.log >/dev/null 2>&1
    fi
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

# ---------- BERSIHKAN SESI TELEGRAM LAMA SEBELUM GATEWAY MULA ----------
# PEPIJAT SEBENAR yang menyebabkan bot "bersambung tetapi tidak menjawab":
#   Connected to Telegram (polling mode)  -> nampak sihat
#   Telegram polling conflict (1/5)      -> 2.5 min kemudian
#   JEJAK MASUK = 0 selama-lamanya
#
# Telegram menyimpan sesi getUpdates selama ~5 minit selepas klien hilang. Bila
# run lama dibatalkan (atau runner mati), sesi itu masih "terbuka" di pelayan
# Telegram. Gateway baharu menyambung, menang getMe, tetapi getUpdates-nya
# di-409 oleh sesi hantu itu — dan ia hanya menunggu 20s x 5 sebelum menyerah.
# Sepanjang tempoh itu bot kelihatan HIDUP (getMe 200) tetapi TIDAK menerima
# mesej, dan tiada apa dalam log menunjukkannya kepada operator.
#
# Penyelesaian: panggil getUpdates dengan offset=-1 dan timeout=0 SEBELUM mula.
# Itu menamatkan sesi hantu di pelayan Telegram serta-merta, jadi gateway
# memperoleh long-poll secara eksklusif sejak saat pertama.
bersih_sesi_telegram() {
  # PELAJARAN MAHAL (13 Nov 2026) — fungsi ini SEKARANG TIDAK DIPANGGIL semasa
  # permulaan biasa. Sebabnya, dengan bukti:
  #
  #   probe-serentak semasa bot HIDUP: bebas=16, konflik=0 (4 minit).
  #   probe-longpoll semasa bot MATI : bebas=6,  konflik=0.
  #   -> TIADA pesaing, tiada sesi hantu. Bot satu-satunya pemegang token.
  #
  #   Tetapi gw_trace.log SENTIASA menunjukkan 'polling conflict (1/5..5/5)'.
  #   Punca: setiap `getUpdates` yang KITA panggil dalam fungsi ini mencipta sesi
  #   baharu yang bertahan ~30-60s. Gateway menyambung selepas itu, lalu di-409
  #   oleh sesi yang kita sendiri baru cipta. Kita menyebabkan konflik yang kita
  #   cuba baiki.
  #
  # Jadi: cukup deleteWebhook (membuang webhook yang merampas long-poll) + jeda.
  # Hanya panggil getUpdates bila benar-benar perlu (lihat panggilan di bawah).
  local hasil_wh
  # drop_pending_updates=true: menurut kod Hermes sendiri (#75017), inilah yang
  # menamatkan sesi getUpdates lain bagi token ini. Tanpa ia, setiap cubaan
  # di-409 serta-merta.
  hasil_wh=$(curl -4 -s -m 15 -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/deleteWebhook" \
    -H "Content-Type: application/json" \
    -d '{"drop_pending_updates":true}' 2>/dev/null)
  case "$hasil_wh" in
    *'"ok":true'*) log "webhook dipadam + sesi lama ditamatkan (drop_pending_updates=true)" ;;
    *) log "AMARAN: deleteWebhook tidak pulang ok — teruskan (mungkin memang tiada webhook)" ;;
  esac
  # Jeda supaya sesi yang baru ditamatkan benar-benar luput sebelum gateway mula.
  # JANGAN probe getUpdates di sini — itu mencipta sesi baharu (lihat nota di atas).
  log "jeda 40s supaya sesi lama luput sebelum gateway menyambung"
  sleep 40
  return 0
}

bersih_sesi_telegram

# ---------- denyut: adakah Telegram boleh dicapai dari sini SEKARANG? ----------
# PEPIJAT SEBENAR: versi lama guna SATU cubaan `curl -4` ke api.telegram.org.
# Runner kadang gagal IPv4 (ConnectError('')) lalu domain bekerja semula — jadi
# ujian tunggal melaporkan "Telegram mati" sedangkan gateway sendiri masih
# long-poll dengan baik, dan watchdog MEMBUNUH gateway sihat.
# Bukti: 'Previous gateway life exited UNCLEANLY (SIGKILL)' berulang setiap ~15 min.
# Diperbaiki: 3 cubaan (IPv4 -> hostname -> IP literal Telegram) sebelum mengaku mati.
telegram_hidup() {
  local code ip
  for cubaan in 1 2 3; do
    code=$(curl -4 -s -o /dev/null -m 12 -w "%{http_code}" \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo 000)
    [ "$code" = "200" ] && return 0
    # cubaan 2: hostname tanpa paksa IPv4 (dual-stack)
    code=$(curl -s -o /dev/null -m 12 -w "%{http_code}" \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo 000)
    [ "$code" = "200" ] && return 0
    # cubaan 3: IP literal Telegram (elak DNS/IPv4 runner yang rosak)
    for ip in 149.154.167.220 149.154.166.110; do
      code=$(curl -s -o /dev/null -m 12 -w "%{http_code}" \
        --resolve "api.telegram.org:443:$ip" \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo 000)
      [ "$code" = "200" ] && return 0
    done
    sleep 3
  done
  return 1
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

  # WAJIB. Sebelum ini pembersihan hanya dijalankan SEKALI di atas fail. Bila
  # gateway mati dan cubaan ini memulakannya semula, sesi long-poll lama masih
  # dipegang di pelayan Telegram -> getUpdates di-409 -> adapter PARKED -> bot
  # bisu walaupun "Connected to Telegram (polling mode)" tercetak.
  # Bukti sebenar 13 Nov 2026 15:47-15:48: cubaan 2 mula gateway, sambung OK,
  # kemudian serta-merta 'polling conflict (1/5)'.
  # WAJIB. Sebelum ini pembersihan hanya dijalankan SEKALI di atas fail. Bila
  # gateway mati dan cubaan ini memulakannya semula, sesi long-poll lama masih
  # dipegang di pelayan Telegram -> getUpdates di-409 -> adapter PARKED -> bot
  # bisu walaupun "Connected to Telegram (polling mode)" tercetak.
  #
  # PEMBETULAN PENTING (13 Nov 2026, bukti probe-serentak):
  #   Probe SERENTAK semasa bot hidup: bebas=16, konflik=0 selama 4 minit.
  #   Bermakna TIADA pesaing langsung. Konflik dalam log datang daripada
  #   PEMBERSIHAN KITA SENDIRI: setiap panggilan getUpdates mencipta sesi baharu
  #   yang bertahan ~30-60s, lalu gateway menyambung dan di-409 oleh sesi itu.
  #
  # Jadi: JANGAN bersih sesi pada setiap cubaan semula. Dalam satu runner yang
  # sama, gateway baharu menggantikan yang lama dengan cepat; Probe getUpdates
  # hanya merosakkan keadaan. Cukup: bunuh yatim, jeda, mula.
  if [ "$cubaan" -gt 1 ]; then
    log "cubaan semula -> bunuh gateway yatim, jeda, kemudian mula (TANPA probe getUpdates)"
    for p in $(ps -eo pid,args 2>/dev/null \
        | grep -F "sys.argv=['hermes','gateway','run']" \
        | grep -v grep | awk '{print $1}'); do
      if [ "$p" != "$$" ] && [ "$p" != "$GW_PID" ]; then
        log "bunuh gateway yatim pid=$p"
        kill -TERM "$p" 2>/dev/null || true
        sleep 3
        kill -9 "$p" 2>/dev/null || true
      fi
    done
    # Jeda ini menggantikan probe: cukup untuk Telegram melepaskan sesi gateway
    # yang baru dibunuh. Tiada getUpdates -> tiada sesi baharu -> tiada 409 palsu.
    log "jeda 45s untuk Telegram melepaskan sesi gateway lama"
    sleep 45
  fi

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
    #
    #     PEPIJAT SEBELUM: satu kegagalan `telegram_hidup` serta-merta membunuh
    #     gateway. Runner GitHub kadang gagal IPv4 sekejap (ConnectError('')) lalu
    #     pulih — akibatnya gateway SIHAT dibunuh setiap ~15 min (SIGKILL berulang)
    #     dan mesej BOZ hilang dalam selang itu. Sekarang perlu DUA kali gagal
    #     berturut-turut (20 min) sebelum bertindak.
    #
    #     PEPIJAT KEDUA (dibaiki 9 Nov 2026): `$MARK` ditetapkan SEBELUM gateway
    #     mula dan TIDAK PERNAH dikemas kini. Selepas log bergerak sekali, syarat
    #     `$BARU -eq $MARK` sentiasa palsu — jadi watchdog TIDAK PERNAH memeriksa
    #     kesihatan selepas minit pertama. Bot boleh tersangkut berjam-jam dengan
    #     `ConnectError('')` sementara pengawasan tidur. Sekarang MARK dikemas kini
    #     selepas setiap pemeriksaan, dan kita periksa kesihatan SETIAP tick 5 minit.
    if [ $(( tick % 5 )) -eq 0 ]; then
      BARU=$(wc -l < "$GW_LOG" 2>/dev/null || echo 0)
      if [ "$BARU" -eq "$MARK" ]; then
        if ! telegram_hidup; then
          GAGAL=$(( ${GAGAL:-0} + 1 ))
          log "watchdog: log beku + Telegram tidak menjawab (gagal $GAGAL/2) — belum bunuh"
          # Kiraan ConnectError dalam tetingkap log terkini: tiga atau lebih
          # bermakna kebocoran fd, bukan blip rangkaian sesaat.
          CE=$(tail -n 200 "$GW_LOG" 2>/dev/null | grep -c "ConnectError" || true)
          if [ "$CE" -ge 3 ]; then
            log "watchdog: $CE ConnectError dalam 200 baris -> kebocoran fd, mula semula"
            bunuh_gateway "$GW_PID"
            break
          fi
          if [ "$GAGAL" -ge 2 ]; then
            log "watchdog: 2 kegagalan berturut -> sambungan benar-benar rosak, mula semula"
            bunuh_gateway "$GW_PID"
            break
          fi
        else
          GAGAL=0
        fi
      else
        # Log bergerak = gateway bekerja. Kemas kini MARK supaya pemeriksaan
        # seterusnya mengukur aktiviti SEJAK titik ini, bukan sejak permulaan.
        MARK=$BARU
        GAGAL=0
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
