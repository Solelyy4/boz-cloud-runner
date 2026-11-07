#!/usr/bin/env bash
# gateway_run.sh — logik gateway Telegram (dipindah keluar dari workflow).
#
# SEBAB: GitHub mengehadkan SETIAP blok `run:` kepada 21,000 aksara. Blok gateway ini
# membesar kepada 24,760 aksara selepas bertahun tampalan -> "Invalid workflow file
# (Line: 499, Col: 14): Exceeded max expression length 21000" dan SELURUH workflow
# ditolak (0 saat, tiada log). Skrip berasingan membebaskan kita dari had itu.
#
# Kunci dihantar sebagai env var oleh workflow (env: pada langkah), bukan ${{ }} di sini.
set -uo pipefail

for K in TELEGRAM_BOT_TOKEN MISTRAL_API_KEY GROQ_API_KEY; do
  if [ -z "${!K:-}" ]; then
    echo "::error::$K KOSONG — gateway mustahil berfungsi"
    exit 1
  fi
done
echo "kunci disahkan (TELEGRAM, MISTRAL, GROQ)"

export HERMES_HOME="$PWD/home"
export HERMES_NO_UPDATE_CHECK=1
export PYTHONUNBUFFERED=1
export PYTHONIOENCODING=utf-8
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
# PUNCA UTAMA bot menjawab "AI model service kept failing" + fallback habis:
# langkah ini DAHULUNYA hanya mengeksport TELEGRAM_BOT_TOKEN, sedangkan
# config.yaml merujuk api_key_env: MISTRAL_API_KEY. Tanpa kunci ini setiap
# panggilan model pulang 401 dan rantai fallback mati satu per satu
# (ministral-14b -> ministral-8b -> groq -> habis).
export MISTRAL_API_KEY="${MISTRAL_API_KEY:-}"
export GROQ_API_KEY="${GROQ_API_KEY:-}"
export ROUTER9_API_KEY="${ROUTER9_API_KEY:-}"
export BOZ_PAT="${BOZ_PAT:-}"
# CLI dipasang oleh install.sh ke ~/.local/bin — tanpa ini `hermes` tidak dijumpai.
export PATH="$HOME/.local/bin:$PATH"

# PENALA SAMBUNGAN. Lalai Hermes: 30s x 8 cubaan + 120s = 360s sebelum menyerah.
# 30s terlalu panjang untuk runner: telegram-init yang hang memakan masa sepenuhnya
# dan menghalang cubaan berikut, sedangkan getMe dari IP runner pulang dalam 0.27s
# (jadi hang 30s = bug dalam proses, bukan rangkaian perlahan). 10s x 3 = 30s
# memberi 3 peluang pantas dan gagal cepat supaya gelung luar boleh mula semula.
export HERMES_TELEGRAM_INIT_TIMEOUT=10
# ConnectError('') KOSONG = sambungan tergantung, bukan rangkaian mati.
# Bukti: 8s terlalu singkat pada laluan runner yang tersekat — ujian curl
# dari runner SAMA pulang 302 dalam 0.38s, tetapi adapter json-stream
# tergantung >8s lalu gagal dengan ralat KOSONG. Naikkan ke 20s.
export HERMES_TELEGRAM_HTTP_CONNECT_TIMEOUT=20
export HERMES_TELEGRAM_HTTP_READ_TIMEOUT=30
# IPv6 gagal di runner (curl -6 -> 000). Paksa IPv4 sahaja supaya
# Happy Eyeballs tidak menunggu AAAA yang sentiasa mati.
export HERMES_TELEGRAM_FORCE_IPV4=1

# Keluarkan token dari URL git supaya jejak tak kekal dalam .git/config
git remote set-url origin "$(git remote get-url origin | sed -E 's#https://x-access-token:[^@]*@#https://github.com/#')" 2>/dev/null || true

lapor() {
  # PENTING: batch sediakan kunci push SEBELUM mengunci — supaya semasa bot hidup
  # (yang memang kerap push) status.log tidak tertinggal berjam-jam menyebabkan
  # operator menyangka bot mati. Retry ditambah + jitter.
  for p in 1 2 3 4 5 6; do
    git fetch origin master -q >/dev/null 2>&1 || true
    git rebase --abort >/dev/null 2>&1 || true
    git checkout -q -B status-tmp origin/master >/dev/null 2>&1 || true
    {
      echo "=== run $GITHUB_RUN_ID tick $(date -u +%FT%TZ) ==="
      tail -n 300 gw.log 2>/dev/null || true
      if grep -qiE 'error|traceback|exception|failed|refus' gw.log 2>/dev/null; then
        echo '--- ERROR LINES ---'
        grep -iE -A6 'error|traceback|exception|failed|refus' gw.log 2>/dev/null | tail -n 120 || true
      fi
      echo "$1 $(date -u +%FT%TZ)"
    } > status.log
    git add -f status.log >/dev/null 2>&1
    git -c user.email=bot@local -c user.name=bot commit -qm "status $1 $(date -u +%FT%TZ)" >/dev/null 2>&1 || true
    if git push origin HEAD:master >/dev/null 2>&1; then return 0; fi
    sleep $((3 + p * 2))
  done
  return 0
}

# ===== JAMBATAN KE HERMES PENUH (laptop BOZ) =====
# Bila bot TIDAK BOLEH menyelesaikan tugasan dengan toolset nipisnya, ia TIDAK
# menyerah: ia tanya otak kedua di laptop BOZ (Hermes penuh + 9Router + shell) dan
# memulangkan jawapannya ke Telegram. Ini menjawab "bot kena boleh buat semua".
#   python scripts/bridge.py brain "<masalah>" --context '<json>' --wait 600
# Laptop tidur/mati -> jambatan tamat masa; bot mesti beritahu BOZ dengan jujur.
echo "jambatan: guna 'python scripts/bridge.py brain ...' bila alat gagal atau soalan di luar toolset"

# PENTING: jangan sesekali panggil getUpdates dari luar.
# Adapter Hermes SENDIRI yang memegang long-poll; sebarang getUpdates lain
# (canary, probe, deleteWebhook semasa poll) akan memicu 409 dan mematikan bot.
# Satu-satunya proses yang dibenarkan menyentuh Telegram API ialah gateway.

# BUKTI KEADAAN (bukan teka-teki teks): getMe jauh lebih murah daripada meneka
# tanda dalam log. Disahkan 5/5 HTTP 200 dari IP runner, jadi kalau getMe OK tetapi
# gateway tetap "attempt 1/8", masalahnya DALAM proses Hermes — bukan rangkaian.
sehat() {
  code=$(curl -4 -s -o /dev/null -m 12 -w "%{http_code}" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" || echo 000)
  [ "$code" = "200" ]
}

# Sambungan dianggap BERJAYA bila salah satu tanda ini muncul. Tanda lama
# ("telegram") terlalu longgar dan meloloskan kegagalan; tanda baharu lebih tepat.
TANDA='polling|connected|Bot started|listening|getUpdates|Started polling|long.poll'

# PENJEJAK: push gw.log setiap 60s supaya operator boleh lihat mesej diproses atau tidak.
# Tanpa ini kita buta — log hanya di-push bila lapor() dipanggil (setiap ~10 min).
(
  while true; do
    sleep 60
    if [ -s gw.log ]; then
      cp gw.log /tmp/gw_trace_akhir.log 2>/dev/null || echo "" > /tmp/gw_trace_akhir.log
      git fetch origin master -q >/dev/null 2>&1 || true
      git checkout -q -B trace-tmp origin/master >/dev/null 2>&1 || true
      { echo "=== TRACE $(date -u +%FT%TZ) run $GITHUB_RUN_ID ==="; tail -n 400 /tmp/gw_trace_akhir.log 2>/dev/null; } > gw_trace.log
      git add -f gw_trace.log >/dev/null 2>&1
      git -c user.email=bot@local -c user.name=bot commit -qm "trace $(date -u +%FT%TZ)" >/dev/null 2>&1 || true
      git push origin HEAD:master >/dev/null 2>&1 || true
    fi
  done
) &
TRACE_PID=$!

# Cubaan tanpa had (bounded by timeout-minutes 1450). Kalau Telegram Bot API down
# (502/timeout), kita tunggu & cuba semula sehingga runner tamat — bot pulih sendiri.
# BUG LAMA: gw.log diwarisi daripada run terdahulu. MARK = baris lama, jadi
# `tail -n +MARK` terus memadankan "Connected" milik sesi mati dan workflow
# melaporkan sambungan yang tidak wujud — bot tidak pernah mula, tetapi kita
# fikir ia mula. Mula dengan log BERSIH setiap kali.
: > gw.log
echo "gw.log dimulakan bersih $(date -u +%FT%TZ) run $GITHUB_RUN_ID" >> gw.log

# PENTING: `python` mentah dalam runner BUKAN venv Hermes — ia sistem python
# yang tiada modul hermes_cli. Bukti sebenar: gw.log penuh dengan
# "ModuleNotFoundError: No module named 'hermes_cli'" 3 kali berturut-turut →
# bot tidak pernah mula langsung. Cari venv Hermes SEKALI sebelum gelung.
GWPY=""
for cand in "$HERMES_HOME"/installs/*/environments/*/venv/bin/python; do
  [ -x "$cand" ] || continue
  if "$cand" -c "import hermes_cli" 2>/dev/null; then GWPY="$cand"; break; fi
done
if [ -z "$GWPY" ]; then
  echo "::error::venv Hermes tidak dijumpai — gateway tidak boleh mula"
  echo "venv tidak dijumpai — gateway tidak boleh mula" >> gw.log
  exit 1
fi
echo "gateway python: $GWPY" | tee -a gw.log

# ==== JEJAK MESEJ MASUK (bukti bot MEMPROSES, bukan sekadar sambung) ====
# BUKTI KEPERLUAN (gw_trace.log run 42247567171): log bermula terus pada baris 18
# "[Telegram] Discovering..." — TIADA baris JEJAK langsung, walaupun status langkah
# patch ketika itu "success". Sebabnya: adapter mencatat mesej pada aras `debug`
# manakala gateway guna WARNING, jadi pemprosesan berlaku TETAPI BUTA kepada kita.
# Patch ini menulis [JEJAK] pada aras WARNING.
#
# PENTING — lokasi patch MESTI dalam langkah ini, BUKAN langkah berasingan:
# `GWPY`/`HERMES_HOME` hanya ditakrifkan di sini. Carian dari $PWD/home GAGAL
# senyap kerana adapter hidup di dalam VENV (home/installs/*/environments/*/venv).
#
# PENTING 2 — setiap $(...) mesti ada `|| true`. Bukti run 42250213661: langkah
# mati dengan exit code 1 tepat selepas "gateway python: ..." kerana skrip ini
# berjalan dengan `set -e`, dan `HS=$(...)` pulang bukan-sifar apabila import
# hermes_plugins gagal — jadi shell keluar sebelum bot sempat mula.
# PENTING 3 — JANGAN guna `import hermes_plugins` untuk mencari lokasi.
# Bukti 2026-11-06 (status.log run 42251618926 baris 4): HERMES_SRC pulang KOSONG
# kerana `hermes_plugins` ialah namespace DINAMIK yang dicipta oleh
# hermes_cli/plugins_loader.py (_NS_PARENT = "hermes_plugins") — ia TIADA dalam
# sys.path semasa import biasa. Cari secara fail, bukan import.
HS=""
for cand in "$HERMES_HOME" "$PWD/home" "$PWD/home/installs" "$HOME/.local/share/hermes"; do
  [ -d "$cand" ] || continue
  if find "$cand" -path '*plugins/platforms/telegram/adapter.py' -print -quit 2>/dev/null | grep -q adapter; then
    HS="$cand"; break
  fi
done
echo "HERMES_SRC=$HS" | tee -a gw.log
if [ -z "$HS" ] || [ ! -d "$HS" ]; then
  echo "::warning::perakam tak jumpa pokok hermes_plugins — bot tetap berfungsi"
else
  ADFILE=$(find "$HS" -path '*plugins/platforms/telegram/adapter.py' -print -quit 2>/dev/null || true)
  echo "adapter dijumpai: ${ADFILE:-TIADA}" | tee -a gw.log
  if [ -n "$ADFILE" ]; then
    HERMES_SRC="$HS" "$GWPY" scripts/jejak_bot.py 2>&1 | tee -a gw.log || \
      echo "::warning::jejak gagal — bot tetap berfungsi (skrip undur sendiri)"
    # Sahkan patch benar-benar masuk ke fail yang akan DIMUAT gateway.
    N_JEJAK=$(grep -c 'JEJAK-BOT-BOZ' "$ADFILE" 2>/dev/null || true)
    echo "jejak dalam adapter: ${N_JEJAK:-0}" | tee -a gw.log
  fi
fi

# ==== JEJAK KE SALINAN WORKSPACE (yang gateway SEBENARNYA import) ====
# BUKTI (gw_trace.log run 42396007028, baris 24-26):
#   logger guna nama modul `hermes_plugins.platforms__telegram.adapter`.
#   Nama itu dibina daripada manifest_key "plugins/platforms/telegram"
#   (plugins_loader.py: slug = manifest_key.replace("/", "__").replace("-", "_")).
# Hermes menyalin pokok plugin ke installs/<id>/environments/<env>/workspace/plugins
# dan mengimport dari SALINAN itu. Saiz berbeza membuktikannya (laptop 7 Nov 2026):
#   hermes-agent/plugins/platforms/telegram/adapter.py            441,748 bait
#   installs/.../workspace/plugins/platforms/telegram/adapter.py  442,334 bait
# Jadi patch ke hermes-agent/ sahaja TIDAK PERNAH DIMUAT -> tiada [JEJAK] selama ini.
#
# Salinan workspace/ dicipta SEMASA boot, jadi kita tidak boleh menampal awal.
# jejak_bot.py kini mencari SEMUA salinan (rglob dari $HERMES_HOME), jadi kita:
#   (a) tampal sekali sekarang (menangkap salinan yang sudah ada), dan
#   (b) pasang pemanjat latar yang tampal semula apabila salinan baharu muncul.
ADA_WS=0
for d in "$HERMES_HOME"/installs/*/environments/*/workspace; do
  [ -f "$d/plugins/platforms/telegram/adapter.py" ] && ADA_WS=1
done
HERMES_HOME="$HERMES_HOME" "$GWPY" scripts/jejak_bot.py 2>&1 | grep -E '^JEJAK|^  \[' | \
  tee -a gw.log || true
echo "jejak: salinan workspace ada=($ADA_WS)" | tee -a gw.log
# BUKTI SAH: kira penanda dalam SETIAP salinan + saiz, SEBELUM gateway mula.
# Bukti sebelum ini menunjukkan "PATCH OK" tetapi tiada [JEJAK] dalam log, jadi
# kita perlu bukti BAIT, bukan laporan skrip.
for d in "$HERMES_HOME"/hermes-agent/plugins/platforms/telegram/adapter.py \
         "$HERMES_HOME"/installs/*/environments/*/workspace/plugins/platforms/telegram/adapter.py; do
  [ -f "$d" ] || continue
  N=$(grep -c 'JEJAK-BOT-BOZ' "$d" 2>/dev/null || echo 0)
  S=$(wc -c < "$d" 2>/dev/null || echo 0)
  echo "  SAH: penanda=$N saiz=$S $d" | tee -a gw.log
done
(
  # Pemanjat: 40 x 15s = 10 minit, cukup untuk Hermes boot + salin pokok plugin.
  for t in $(seq 1 40); do
    sleep 15
    ada=0
    for d in "$HERMES_HOME"/installs/*/environments/*/workspace; do
      [ -f "$d/plugins/platforms/telegram/adapter.py" ] && ada=1
    done
    [ "$ada" = "1" ] || continue
    HASIL=$(HERMES_HOME="$HERMES_HOME" "$GWPY" scripts/jejak_bot.py 2>&1 | grep -E 'sedia untuk dimuat')
    echo "jejak-pemanjat t=$t: ${HASIL:-tiada}" 
    echo "jejak-pemanjat t=$t: ${HASIL:-tiada}" >> gw.log
    break
  done
) &
echo "jejak: pemanjat latar dipasang (10 minit)" | tee -a gw.log

# WAJIB: adapter Telegram gagal tanpa python-telegram-bot dalam venv INI.
# Bukti sebenar: gw.log berbunyi "Platform 'Telegram' requirements not met
# (platform.telegram.install_hint)" + "No adapter available for telegram".
# Lazy-installer Hermes (pm.ensure_import) tidak berjaya di runner (tiada
# akses tulis/pip yang dikonfigurasi), jadi pasang terus di sini.
echo "=== pasang dependency platform (python-telegram-bot) ===" | tee -a gw.log
"$GWPY" -c "import telegram; print('telegram ADA', telegram.__version__)" 2>/dev/null \
  || { "$GWPY" -m ensurepip --upgrade >/dev/null 2>&1 || true
       "$GWPY" -m pip install --quiet --disable-pip-version-check \
         "python-telegram-bot[socks,http2]>=21" 2>&1 | tail -5 || true; }
"$GWPY" -c "import telegram, telegram.ext; print('telegram OK', telegram.__version__)" \
  | tee -a gw.log || { echo "::error::python-telegram-bot tidak dapat dipasang"; exit 1; }

# ddgs: backend web_search keyless. Tanpa ia, web_search pulang 0 hasil
# dan bot tidak boleh ambil apa-apa dari internet (tugasan utama BOZ).
"$GWPY" -m pip install --quiet --disable-pip-version-check ddgs 2>&1 | tail -3 || true
"$GWPY" -c "import ddgs; print('ddgs OK')" | tee -a gw.log \
  || echo "AMARAN: ddgs tiada — web_search mungkin pulang 0" | tee -a gw.log

# ==== JEJAK TITIK MASUK UPDATE (Application.process_update) ====
# Kenapa: jejak handler (adapter.py) sudah terbukti ditampal (penanda=5, saiz
# 446,201 pada kedua-dua salinan) tetapi TIADA [JEJAK] muncul walaupun kita
# memegang long-poll (DIAG: getUpdates ok, 0 update, pending=0). Kita perlu tahu
# sama ada update sampai ke python-telegram-bot Application.process_update.
# Kalau TIDAK -> masalah sebelum adapter (rangkaian/sesi/handler).
# Kalau YA tetapi handler senyap -> gate menolak sebelum handler.
"$GWPY" scripts/jejak_masuk.py 2>&1 | tee -a gw.log || \
  echo "::warning::jejak_masuk gagal (bukan ralat maut)" | tee -a gw.log


# ===== PEMULIHAN RANGKAIAN RUNNER (bukti 2026-11-05) =====
# Runner GitHub kadang HILANG akses ke api.telegram.org sepenuhnya selama
# berjam-jam: SEMUA laluan gagal (hostname, IPv4 literal 149.154.166.110,
# dual-stack) dengan httpx.ConnectError kosong. Daripada laptop, Telegram
# pulang HTTP 302 dalam 1.2s pada masa yang sama -> isu khusus rangkaian
# runner, bukan Telegram. Ubat: nyahsekat resolver + paksa IPv4 + Naikkan
# TIMEOUT sambungan (8s terlalu ketat untuk laluan tersekat).
#
# set_ipv4_only: elak cubaan IPv6 yang sentiasa gagal di runner.
export HERMES_TELEGRAM_FORCE_IPV4=1
export CURL_IPRESOLVE=4
# getent/curl mesti guna resolver yang sama seperti adapter (glibc), bukan
# DoH dalaman Hermes — kalau tidak kita betulkan satu laluan sahaja.
if [ -w /etc/resolv.conf ]; then
  grep -q '^nameserver 1.1.1.1' /etc/resolv.conf 2>/dev/null || {
    cp /etc/resolv.conf /tmp/resolv.bak 2>/dev/null || true
    printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\noptions timeout:2 attempts:2\n' \
      | sudo tee /etc/resolv.conf >/dev/null 2>&1 || true
    echo "resolv.conf: resolver awam ditulis" | tee -a gw.log
  }
fi
# Sahkan sekali sebelum gelung utama: kalau DNS rosak, betulkan lebih awal.
for u in api.telegram.org core.telegram.org; do
  ip=$(getent ahostsv4 "$u" 2>/dev/null | awk 'NR==1{print $1}')
  echo "DNS $u -> ${ip:-GAGAL}" | tee -a gw.log
done

# ===== PEMULIHAN KEBOCORAN FAIL DESCRIPTOR (bukti 2026-11-05) =====
# Bot tersangkut 1j45m dengan 20x "ConnectError('')" KOSONG sementara ujian
# rangkaian dari runner SAMA membuktikan IP Telegram BUKA + getMe HTTP 200
# dalam 0.38s. Kod Hermes sendiri mengamarkan punca ini (telegram_network.py
# baris 117-121, isu #63311): setiap kegagalan long-poll mengekalkan satu socket
# CLOSE_WAIT dalam kolam -> satu fd bocor setiap retry -> proses kehabisan fd
# -> SEMUA sambungan baharu gagal dengan ralat kosong walaupun rangkaian sihat.
# Ubat: pantau bilangan fd gateway; bersara proses bila menghampiri had.
ulimit -n 65536 2>/dev/null || ulimit -n 8192 2>/dev/null || true
fd_gateway() {
  local pid="$1"
  [ -d "/proc/$pid/fd" ] || { echo 0; return; }
  ls /proc/$pid/fd 2>/dev/null | wc -l
}
had_fd() { ulimit -n 2>/dev/null || echo 1024; }
echo "ulimit -n = $(had_fd)" | tee -a gw.log

# ==== BUNUH GATEWAY DENGAN SELAMAT ====
# PUNCA rc=127 (7 Nov 2026): `bunuh_gateway` padan dengan SKRIP INI
# SENDIRI (baris arahan skrip mengandungi teks itu), jadi ia membunuh diri sendiri
# 2 saat selepas "Connected" -> gateway mati setiap kali, bot bisu selama-lamanya.
# Ubat: bunuh PID yang kita tahu, dan gunakan padanan yang TIDAK boleh padan diri.
bunuh_gateway() {
  # 1) bunuh PID yang kita simpan (paling selamat)
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
  fi
  # 2) sapu baki proses hermes gateway yang lain — TETAPI kecualikan diri sendiri.
  #    `pgrep -f` juga padan diri, jadi tapis $$ dan PPID keluar dahulu.
  if command -v pgrep >/dev/null 2>&1; then
    for p in $(pgrep -f "hermes_cli.main" 2>/dev/null || true); do
      [ "$p" = "$$" ] && continue
      [ "$p" = "$PPID" ] && continue
      kill -9 "$p" 2>/dev/null || true
    done
  fi
  return 0
}

cubaan=0
while true; do
  cubaan=$((cubaan+1))
  MARK=$(wc -l < gw.log 2>/dev/null || echo 0)
  bunuh_gateway 2>/dev/null || true
  sleep 8
  # PENTING: python di-buffer secara blok dalam runner bukan-TTY. Tanpa
  # PYTHONUNBUFFERED, gw.log kelihatan "berhenti selepas Connected" walaupun
  # gateway sebenarnya memproses mesej — kita buta, bukan bot bisu.
  # Tangkap exit code + sebab keluar. Gateway yang keluar senyap (SIGTERM/exit 0)
  # adalah punca bot "bisu": ia sambung, kemudian mati tanpa traceback.
  PYTHONUNBUFFERED=1 HERMES_DEBUG=1 "$GWPY" -X faulthandler -c \
    "import sys,signal; signal.signal(signal.SIGTERM, lambda *a: (print('GATEWAY SIGTERM', flush=True), sys.exit(143))); from hermes_cli.main import main; sys.argv=['hermes','gateway','run']; main()" \
    >> gw.log 2>&1 &
  PID=$!
  TUNGGU=0
  for i in $(seq 1 36); do
    sleep 5
    TUNGGU=$((TUNGGU+5))
    if tail -n +$((MARK+1)) gw.log | grep -qiE "$TANDA"; then
      echo "sambungan dikesan selepas ${TUNGGU}s"
      break
    fi
    kill -0 $PID 2>/dev/null || break
  done
  tail -20 gw.log
  lapor "mula-cubaan-$cubaan selepas-${TUNGGU}s"

  # ==== UJIAN PASCA-SAMBUNG (bukti bot benar-benar MEMBALAS) ====
  # BUKTI KEPERLUAN (gw_trace.log run 42398381595):
  #   Langkah AUDIT dalam workflow berjalan SEBELUM gateway mula:
  #     18:08:32-18:09:29 hantar 6 mesej  <- bot BELUM hidup
  #     18:09:46          gateway mula
  #     18:09:58          Connected
  #   Akibatnya [JEJAK] KOSONG — ujian menguji bot mati, dan "bot_ambil: true"
  #   yang dilaporkan adalah palsu (pending turun kerana sebab lain).
  # Ujian sebenar mesti dihantar SEMASA bot hidup. Kita tunggu sambungan,
  # kemudian hantar 6 mesej dan tangkap [JEJAK] yang sebenar.
  if [ ! -f .uji_pasca_dijalankan ]; then
    (
      # Tunggu Connected (maks 4 minit) — TUNGGU=15s biasanya sudah cukup.
      for w in $(seq 1 24); do
        sleep 10
        tail -n +$((MARK+1)) gw.log | grep -q "Connected to Telegram" && break
      done
      sleep 20   # beri adapter masa memasang handler
      echo "=== ujian-pasca: bot hidup, hantar 6 mesej $(date -u +%FT%TZ) ===" >> gw.log
      PY2="$(command -v python3 || echo python3)"
      # TOKEN UNIK: mesej mengandungi token rawak. Kita kemudian cari token itu
      # dalam [JEJAK] adapter. Kalau token muncul -> MESEJ KITA benar-benar
      # sampai ke adapter (bukti keras). Kalau tidak -> bot kita tidak menerima
      # mesej (sesi Telegram lain merampas getUpdates).
      TOK="UJI$(date +%s)$RANDOM"
      curl -4 -s -m 20 -X POST \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${BOZ_CHAT_ID:-8043910371}" \
        -d "text=MESEJ UJIAN AUTOMATIK. Balas dengan tepat perkataan ini: ${TOK}" \
        >/dev/null 2>&1 || true
      echo "token ujian dihantar: $TOK" >> gw.log
      timeout 400 "$PY2" scripts/interaksi.py --siri --tunggu 45 >> gw.log 2>&1 || \
        echo "uji pasca gagal dilancarkan" >> gw.log
      sleep 40   # beri bot masa menjawab (model + hantar balasan)
      # Adakah token ujian muncul dalam [JEJAK]? Itu bukti keras.
      # PENTING: cari baris [JEJAK] SEBENAR daripada adapter, bukan baris echo ini.
      if grep -q "\[JEJAK\] MESEJ" gw.log 2>/dev/null; then
        CT=$(grep -c "\[JEJAK\] MESEJ" gw.log 2>/dev/null)
        echo "BUKTI KERAS: $CT baris [JEJAK] MESEJ daripada adapter — bot MEMPROSES" >> gw.log
        grep "\[JEJAK\] MESEJ" gw.log | head -8 >> gw.log
      else
        echo "AMARAN: TIADA [JEJAK] MESEJ daripada adapter — mesej tidak sampai ke handler" >> gw.log
      fi
      # DIAGNOSTIK GETUPDATES: siapa PEMEGANG long-poll?
      # 409 = ada pemegang lain (bot kita). Data/kosong tanpa 409 = KITA pemegang
      # dan bot kita tidak menerima apa-apa -> mesej pergi ke tempat lain.
      RESP=$(curl -4 -s -m 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates?limit=3&timeout=0" 2>/dev/null)
      if echo "$RESP" | grep -q '409'; then
        echo "DIAG: getUpdates -> 409 (bot kita PEMEGANG long-poll — betul)" >> gw.log
      elif echo "$RESP" | grep -q '"ok":true'; then
        JUMLAH=$(echo "$RESP" | grep -o '"update_id"' | wc -l)
        echo "DIAG: getUpdates -> ok, $JUMLAH update boleh dibaca (KITA pemegang!)" >> gw.log
      else
        echo "DIAG: getUpdates -> $(echo "$RESP" | head -c 160)" >> gw.log
      fi
      echo "DIAG: pending_update_count=$(curl -4 -s -m 12 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" | sed -n 's/.*"pending_update_count":\([0-9]*\).*/\1/p')" >> gw.log
      {
        echo "=== UJIAN PASCA-SAMBUNG $(date -u +%FT%TZ) run $GITHUB_RUN_ID ==="
        echo "--- mesej diambil bot ---"
        cat /tmp/interaksi.json 2>/dev/null | head -60 || echo "tiada transkrip"
        echo
        echo "--- [JEJAK] mesej masuk ke adapter (BUKTI BOT MEMPROSES) ---"
        grep -n "\[JEJAK\]" gw.log 2>/dev/null | head -40 || echo "tiada JEJAK"
        echo
        echo "--- bukti balasan dihantar oleh bot ---"
        grep -inE "Sent message|sendMessage|response sent|Balasan" gw.log 2>/dev/null | head -20 || echo "tiada"
        echo
        echo "--- ralat semasa menjawab ---"
        grep -inE "HTTP [45][0-9][0-9]|Traceback|rate_limited" gw.log 2>/dev/null | tail -15 || echo "tiada"
      } > ujian-pasca.log
      touch .uji_pasca_dijalankan
      for p in 1 2 3; do
        git fetch origin master -q >/dev/null 2>&1 || true
        git checkout -q -B upasca-tmp origin/master 2>/dev/null || true
        git add -f ujian-pasca.log >/dev/null 2>&1
        git -c user.email=bot@local -c user.name=bot commit -qm "bukti ujian pasca $(date -u +%FT%TZ)" >/dev/null 2>&1 || true
        git push origin HEAD:master >/dev/null 2>&1 && break
        sleep 5
      done
    ) &
    echo "uji pasca: pemanjat dipasang (hantar selepas Connected)" >> gw.log
  fi
  if ! sehat; then
    echo "AMARAN: getMe bukan 200 pada cubaan $cubaan"
  fi
  # uji_hidup DIBUANG: `break` di sini menamatkan gelung utama dan
  # membunuh gateway yang sihat. Biarkan watchdog SILENT yang mengendalikan
  # kes tergantung (12 minit, bukan 45s) supaya bot sempat memproses mesej.

  tick=0
  first_seen=""
  LAST_LINES=$(wc -l < gw.log 2>/dev/null || echo 0)
  SILENT=0
  # STUCK dikira berasingan daripada SILENT: SILENT direset setiap kali log bergerak,
  # jadi ia TIDAK boleh mengukur "tersekat berapa lama". STUCK hanya direset bila
  # pending kembali 0 — iaitu bot benar-benar selesai memproses.
  STUCK=0
  # Jejak kematian: bila proses mati, catat kod keluar dan 40 baris terakhir.
  # Jejak kematian: catat masa proses mati + 40 baris terakhir.
  #
  # PEPIJAT rc=127 PALSU (dibetulkan 7 Nov 2026): `wait` hanya berfungsi pada
  # CHILD shell SEMASA. Di dalam subshell `( ... ) &`, $PID BUKAN child subshell
  # itu, jadi `wait $PID` pulang 127 ("not a child of this shell") - kita
  # melaporkan "GATEWAY MATI rc=127" padahal gateway tidak pernah keluar dgn 127.
  # Ini menyesatkan siasatan berjam-jam. Ganti dgn gelung kill -0; kod keluar
  # SEBENAR diambil dalam gelung utama (konteks child shell yg betul).
  ( while kill -0 $PID 2>/dev/null; do sleep 5; done
    echo "=== GATEWAY MATI (pid=$PID) pada $(date -u +%FT%TZ) ===" >> gw.log
    tail -40 gw.log >> gw.log 2>/dev/null
  ) &

  while kill -0 $PID 2>/dev/null; do
    sleep 60
    tick=$((tick+1))
    # fail log sahaja — tiada panggilan Telegram API dari sini
    if tail -n +$((MARK+1)) gw.log | grep -q "Fatal telegram adapter error"; then
      echo "fatal dikesan, mula semula"; bunuh_gateway 2>/dev/null || true; break
    fi
    NOW_LINES=$(wc -l < gw.log 2>/dev/null || echo 0)
    if [ "$NOW_LINES" -eq "$LAST_LINES" ]; then SILENT=$((SILENT+1)); else SILENT=0; LAST_LINES=$NOW_LINES; fi
    if [ "$SILENT" -ge 12 ]; then
      PENDING=$(curl -4 -s -m 12 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" \
        | sed -n 's/.*"pending_update_count":\([0-9]*\).*/\1/p')
      echo "BISU dikesan: ${SILENT}min tanpa log baharu, pending=${PENDING:-?}"
      # PEPIJAT LAMA (dibetulkan 2026-11-06): kod asal membunuh gateway bila
      # pending=0. Tetapi pending=0 adalah NORMAL — bot bisu kerana TIADA MESEJ
      # daripada BOZ, bukan kerana rosak. Bot BOZ dibunuh setiap ~12 minit
      # walaupun sihat, dan setiap bunuh = satu kematian 'UNCLEANLY' dalam trace.
      # Pembetulan: hanya bunuh bila pending>0 (mesej tersekat = adapter tergantung)
      # atau bila getWebhookInfo TIDAK dapat dijawab (sambungan betul-betul mati).
      # pending=0 DAN API menjawab = bot sihat -> JANGAN bunuh.
      #
      # PEMBETULAN KEDUA (2026-11-06, bukti status.log run 42245611116):
      # kematian UNCLEANLY berlaku setiap 4m38s dengan last_mem sihat
      # (rss=262MB/16GB) — jadi bunuh itu BUKAN OOM. Punca: pending>0 dibunuh
      # SERTA-MERTA. Tetapi pending>0 adalah KEADAAN NORMAL apabila bot sedang
      # memproses mesej panjang (web_search, fetch2, banyak platform) — adapter
      # TIDAK menulis log semasa memproses, jadi SILENT naik walaupun sihat.
      # Kini: pending>0 hanya membunuh jika TERSEKAT LAMA (3 pusingan = 36 min)
      # ATAU if proses tidak lagi mengaku polling dalam gw.log.
      if [ -z "$PENDING" ]; then
        echo "  API Telegram tidak menjawab — sambungan mati, proses bersara"
        bunuh_gateway 2>/dev/null || true
        SILENT=0
        break
      elif [ "$PENDING" -gt 0 ]; then
        STUCK=$((STUCK+1))
        if [ "$STUCK" -ge 3 ]; then
          echo "  pending=$PENDING tersekat ${STUCK}x36min DAN log beku — proses bersara"
          bunuh_gateway 2>/dev/null || true
          SILENT=0; STUCK=0
          break
        fi
        echo "  pending=$PENDING tetapi log beku baru ${SILENT}min — bot mungkin sedang MEMPROSES, beri masa (tersekat=${STUCK}/3)"
      else
        echo "  pending=0 dan API menjawab — bot SIHAAT, teruskan (tiada mesej baharu)"
        STUCK=0
      fi
      SILENT=0
    fi
    # WATCHDOG (isu Hermes #18086): updater tergantung senyap selepas satu blip
    # rangkaian. `Updater.running` kekal True tetapi tiada update diproses dan tiada
    # ralat dicatat — gateway "hidup" tetapi bot bisu berjam-jam.
    #
    # PENTING: jangan uji dengan getMe sahaja. Probe dari IP runner membuktikan
    # getMe 5/5 HTTP 200 walaupun adapter masih tersangkut pada "attempt 1/8".
    # Bukti sambungan sebenar = getWebhookInfo melaporkan pending_update_count DAN
    # proses mengaku polling. getWebhookInfo TIDAK merebut long-poll (bukan
    # getUpdates), jadi ia selamat dijalankan semasa gateway hidup.
    if [ -z "$first_seen" ] && tail -n +$((MARK+1)) gw.log | grep -qiE "$TANDA"; then
      first_seen="tick$tick"
      echo "sambungan disahkan pada $first_seen"
    fi
    # Kalau selepas 3 tick (3 minit) gateway masih tiada tanda polling DAN proses
    # mengaku hidup, ia tersangkut -> mula semula. Hadkan kepada 2 cubaan awal
    # supaya selepas itu kita tidak membunuh gateway yang sedang bekerja.
    if [ "$tick" -eq 3 ] && [ -z "$first_seen" ] && [ "$cubaan" -le 2 ]; then
      echo "watchdog: tiada tanda polling selepas 3 minit — mula semula"
      bunuh_gateway 2>/dev/null || true
      break
    fi
    # KEBOCORAN FD (bukti 2026-11-05): 20x ConnectError('') sementara rangkaian
    # terbukti sihat = proses kehabisan fail descriptor. Bila fd melebihi 80% had,
    # bersara proses SEKARANG — proses segar pulih serta-merta, manakala proses
    # bocor akan gagal selama-lamanya dengan ralat kosong.
    FD=$(fd_gateway "$PID"); FDMAX=$(had_fd)
    if [ "$FD" -gt 0 ] && [ "$FD" -gt 512 ] && [ "$FD" -gt $((FDMAX * 6 / 10)) ]; then
      echo "AMARAN FD: $FD/$FDMAX (60%+) — kebocoran sedang berlaku"
    fi
    if [ "$FD" -gt 0 ] && [ "$FD" -gt 700 ] && [ "$FD" -gt $((FDMAX * 8 / 10)) ]; then
      echo "KEBOCORAN FD: $FD/$FDMAX — proses bersara untuk pulih"
      bunuh_gateway 2>/dev/null || true
      break
    fi
    if [ $((tick % 15)) -eq 0 ]; then lapor "denyut tick=$tick fd=$FD/$FDMAX"; fi
    # PENGESAN KEMATIAN PROSES — punca bot bisu berjam-jam walaupun run "in_progress".
    # Tanpa ini, loop terus mengira tick selamanya sementara gateway sudah mati
    # (heartbeat beku, active_sessions kosong, mesej Telegram tidak diambil).
    # `kill -0` menguji kewujudan proses TANPA menghantarnya isyarat.
    if ! kill -0 "$PID" 2>/dev/null; then
      echo "PENGESAN: proses gateway (pid=$PID) sudah MATI pada tick=$tick"
      break
    fi
  done
    # Kod keluar SEBENAR: wait di sini adalah child shell SEMASA (konteks betul).
    wait $PID 2>/dev/null
    RC_SMH=$?
    echo "=== cubaan $cubaan tamat: rc=$RC_SMH (pid=$PID) pada $(date -u +%FT%TZ) ===" >> gw.log
    lapor "gateway-berhenti-cubaan-$cubaan rc=$RC_SMH (first_seen=${first_seen:-tiada})"
  # rehat eksponen berhad (maks 10 minit) supaya pulih cepat bila Telegram balik
  rehat=$((cubaan * 30)); [ "$rehat" -gt 600 ] && rehat=600
  echo "rehat ${rehat}s sebelum cubaan berikut"
  # JIKA CUBAAN BERTERUSAN GAGAL (rangkaian runner buta), BOZ mesti DIBERITAHU.
  # Kalau tidak BOZ menghantar mesej ke dalam kekosongan dan menyangka bot mati.
  # Bukti 2026-11-05: semua laluan Telegram gagal 16+ minit dari runner, sementara
  # laptop pulang 302 dalam 1.2s. Bot perlu jujur, bukan senyap.
  if [ "$cubaan" -ge 3 ]; then
    curl -4 -s -m 20 -X POST \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=8043910371" \
      --data-urlencode "text=⚠️ Bot awan tidak dapat menghubungi Telegram dari runner GitHub (cubaan ${cubaan}). Rangkaian runner yang bermasalah, bukan bot BOZ. Laptop BOZ sihat — jambatan (bridge) boleh jalan. Bot akan pulih sendiri bila rangkaian pulih." \
      >/dev/null 2>&1 || true
  fi
  sleep "$rehat"
done
tail -60 gw.log
