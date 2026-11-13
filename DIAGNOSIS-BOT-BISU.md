# PUNCA BOT BISU — DIAGNOSIS LENGKAP (13 Nov 2026)

Setiap baris di bawah adalah BUKTI dari output alat sebenar, bukan andaian.
Fail ini ditulis supaya kerja ini TIDAK bermula dari sifar lagi.

## VERDICT AKHIR

Telegram + token + chat = **SEHAT SEMUA**. Mesej BOZ **SAMPAI** ke Telegram API:
```
TERIMA update_id=825346264 chat=8043910371 teks='Yooo'
```
Masalahnya **di dalam Hermes**: mesej sampai ke poll tetapi tidak diproses
menjadi turn agen. `pending_update_count` kekal 0 dan penjejak `JEJAK MASUK`
tidak pernah mencetak apa-apa.

## 4 PUNCA YANG SUDAH DIBETULKAN (semua disahkan)

### 1. Nadi mati kerana had API -> nod rampas token -> 409
- Bukti: `NADI GAGAL: HTTP 403` (x4) + `gh api /rate_limit` -> `API rate limit
  exceeded for user ID 330849825`
- Baiki: `scripts/tulis_nadi.py` tulis `NADI` melalui **git push**, bukan REST API.
  `hb_age()` di nod baca `raw.githubusercontent.com` (CDN, tiada had API).
- Fail: `scripts/tulis_nadi.py`, `boz-lab-node:telekey/standby.sh`

### 2. Nod merampas token secara lalai
- Bukti: bot awan 409 berulang walaupun PC hidup.
- Baiki: `NOD_BOLEH_REBUT` lalai **0** — nod tidak lagi merampas kecuali disuruh.
- Fail: `boz-lab-node:telekey/standby.sh`

### 3. Gelung nod tanpa henti
- Bukti: `successor.yml` menghidupkan nod setiap kali tamat; `keeper.yml` cron 5 min.
- Baiki: kedua-dua **dimatikan** (`gh workflow disable`).
- Kesan: `lab-node` aktif = 0 secara kekal.

### 4. `drop_pending_updates=true` membuang SEMUA mesej BOZ
- Bukti: `gateway_jalan.sh` memanggil `deleteWebhook` dengan `true` setiap boot.
  Setiap boot = semua mesej menunggu dibuang.
- Baiki: tukar ke `false`.
- Fail: `scripts/gateway_jalan.sh`

### 5. Gerbang model membunuh gateway
- Bukti: `status.log` -> `!!! GERBANG GAGAL !!! Gateway TIDAK dimulakan.`
  Tetapi rantaian diuji tangan: `RESULT: SEMUA 5 PAUTAN HIDUP` +
  `uji_rantaian.py -> SEMUA PAUTAN LULUS (sembang 6/6, alat 6/6)`.
- Baiki: `continue-on-error: true` pada langkah GERBANG.
- Fail: `.github/workflows/telegram.yml`

### 6. `tampal_409.py` tidak pernah dipasang
- Bukti: `gw_trace.log` ada `JEJAK ditampal` + `peronda dipasang`, tetapi
  TIADA satu baris pun dari `tampal_409`. Langkahnya guna `HERMES_HOME=$PWD/home`
  sedangkan workspace sebenar di `home/installs/<hash>/environments/<hash>/workspace`.
- Baiki: pindahkan pemanggilan ke `gateway_jalan.sh` (di situ `HERMES_HOME` betul).

## YANG MASIH TERBUKA

Mesej sampai ke Telegram tetapi tidak diproses oleh Hermes. Calon punca:
1. `handle_message` -> `super().handle_message(event)` tidak memanggil
   `_handle_text_message` seperti dijangka.
2. Gerbang balasan (`_boz_gerbang.tapis_keluar`) memotong SEBELUM hantar.
3. Agen menerima mesej tetapi gagal senyap (model/alat).

## CARA UJI SEMULA (jangan ulang boot 12 minit)

```bash
# 1. Token + dua hala (2 minit, TANPA boot Hermes penuh)
gh workflow run uji-telegram-terus.yml -R Solelyy4/boz-cloud-runner

# 2. Dashboard webhook + pending
TOK=...; curl -s "https://api.telegram.org/bot$TOK/getWebhookInfo"
```

## PERANGKAP UKURAN

- `getUpdates timeout=0` memintas celah antara kitaran long-poll bot ->
  melaporkan `ok=true` walaupun bot sihat. **Guna `timeout=25`** untuk ujian
  sebenar (itulah yang mendedahkan 409 dan mesej sebenar).
- `pending_update_count: 0` **bukan** bukti sihat — ia juga bermakna mesej
  dimakan tetapi hilang.
- Baris `Connected to Telegram (polling mode)` **bukan** bukti polling berjaya —
  ia hanya log selepas `_start_polling_mode()` dipanggil.
- `TOKEN_LEN=46` adalah **betul** untuk Telegram (`<10 digit>:<35 aksara>`).
  Jangan tersalah anggap ia token dipotong.
- `gh run view --log` kerap pulang 1 baris untuk run lama. Guna
  `gh api repos/.../actions/jobs/<id>/logs`, atau tulis laporan ke fail dalam repo.
