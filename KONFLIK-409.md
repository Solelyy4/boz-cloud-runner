# KONFLIK 409 — PUNCA SEBENAR & PEMBAIKAN

**Tarikh:** 13 November 2026
**Gejala:** Bot Telegram kelihatan hidup tetapi **BISU** — semua mesej BOZ hilang.

---

## 1. Gejala

`gw_trace.log` menunjukkan urutan ini pada setiap run:

```
17:02:00  [Telegram] Connected to Telegram (polling mode)
17:02:01  SAMBUNG OK selepas 40s (bukti: baris 'Connected to Telegram')
17:02:05  [Telegram] Telegram polling conflict (1/5) — previous session still held open
17:02:31  [Telegram] Telegram polling conflict (2/5) — previous session still held open
17:02:58  [Telegram] Telegram polling conflict (3/5) — previous session still held open
          (sehingga 5/5, kemudian "Fatal telegram adapter error: telegram_polling_conflict")
17:00:05  [Telegram] telegram is parked after a non-retryable error
          -> gateway DEGRADED, tiada platform mesej
```

Bot "hidup" — `getMe` pulang 200, log tulis "Connected to Telegram" — tetapi ia
**tidak menerima satu pun mesej** selama ~200 saat, kemudian adapter PARKED dan
bot mati. BOZ hantar mesej, tiada balasan.

---

## 2. Jalan yang salah (jangan ulang)

**Percubaan 1** menyalahkan "sesi hantu" dan menambah pembersihan `getUpdates`
20 x 15s. Itu **memburukkan** keadaan:

> Setiap panggilan `getUpdates` yang kita buat mencipta sesi baharu di pelayan
> Telegram yang mengambil 30 sampai 60 saat untuk luput. Gateway menyambung
> selepas itu, lalu di-409 oleh sesi yang kita sendiri baru cipta.

Kita jadi punca konflik yang kita cuba baiki.

**Percubaan 2** menampal `_rebuild_app_for_retry()` pada adapter (bina semula
objek `Application` PTB sebelum cubaan semula). Itu pembaikan munasabah dan kekal
dalam kod sebagai pertahanan tambahan, tetapi ia **tidak menyelesaikan masalah
ini** kerana masalah sebenar bukan dalam adapter.

---

## 3. Diagnostik yang menemui punca

Hipotesis awal: "ada proses lain memakai token yang sama". Diuji dengan probe:

| Probe | Bila dijalankan | Keputusan |
|---|---|---|
| `probe-longpoll` | Bila bot **MATI** | `bebas=6, konflik=0` |
| `probe-serentak` | Bila bot **HIDUP** (4 minit) | `bebas=16, konflik=0` |

Kedua-duanya bersih, **termasuk** semakan 4 repo BOZ. Ini mengelirukan —
sehingga pemeriksaan yang lebih luas mendedahkan pesaing di **repo yang berbeza**:

```
boz-lab-node / ephemeral-node : in_progress sejak 14:01 (180 minit)
```

---

## 4. PUNCA SEBENAR

Repo `Solelyy4/boz-lab-node` menjalankan `telekey/standby.sh` — **penunggu** yang
memerhati nadi PC di gist:

```
HB_URL = https://gist.githubusercontent.com/Solelyy4/d5cdf07.../raw/alive
FRESH  = 180 saat
```

Logiknya (komen dalam fail itu sendiri):

> *Telegram hanya benarkan SATU poller per token. TeleKey kau sudah poll di PC.
> Jadi nod ini bukan pengganti — ia PENUNGGU:*
> *PC hidup -> nod senyap, TeleKey di PC yang layan pengguna*
> *PC mati -> nod ambil alih dalam ~3-4 minit*

**Bukti nadi pada 13 Nov 2026 16:56 UTC:**

```
nadi mentah  = 1794468509
sekarang     = 1794588990
umur nadi    = 120,481 saat = 33.5 JAM   (had = 180 saat)
```

Nod itu percaya PC "mati sejak 33 jam" lalu **merampas token Telegram**.
`telekey/telekey.py` baris 2849 membaca `TELEGRAM_BOT_TOKEN` — **token yang
SAMA** dengan bot awan.

Rantai lengkapnya:

```
nadi basi 33 jam
  -> nod rampas TELEGRAM_BOT_TOKEN
  -> bot awan poll token sama -> 409
  -> adapter PARKED -> bot BISU
  -> ensure_cloud.sh (cron 15 min) lihat gateway mati
  -> mula semula -> 409 lagi -> GELUNG ABADI
```

**Kenapa tiada siapa perasan:** tiada sesiapa **menulis** nadi itu. Grep seluruh
laptop dan semua repo mendapati `standby.sh` hanya **membaca** nadi. Penulis
tidak pernah wujud — reka bentuk itu tidak dilengkapkan.

---

## 5. PEMBAIKAN

`scripts/tulis_nadi.py` — penulis nadi yang hilang. Ditulis setiap **45 saat**
(had nod 180s, jadi 4x margin). Dipasang dalam `gateway_jalan.sh` sebagai proses
latar, jadi selagi gateway hidup, nadi dikemas kini dan nod kekal senyap.

Setiap tulisan **disahkan semula** dengan membaca gist kembali — bukan sekadar
percaya HTTP 200.

---

## 6. BUKTI PEMBAIKAN BERFUNGSI

**Nadi:**

| | Sebelum | Selepas |
|---|---|---|
| Umur nadi | 120,481 saat (33.5 jam) | **25 saat** |
| Tulisan disahkan | 0 | 12 tulisan, semua `NADI OK` |

**Log gateway selepas pembaikan (run 43470508562, sejak 17:15:27):**

```
17:15:27  penulis nadi dipasang (pid=3716, setiap 45s)
          NADI OK: 1794590127 (masa epoch ditulis dan disahkan)
          NADI OK: 1794590173 (masa epoch ditulis dan disahkan)
17:16:26  [Telegram] Connected to Telegram (polling mode)
17:16:27  SAMBUNG OK selepas 20s

konflik: 0
parked : 0
```

Sebelum pembaikan, setiap run menunjukkan `polling conflict (1/5..5/5)` dan
berakhir dengan `parked`. **Selepas pembaikan: 0 konflik, 0 parked.**

---

## 7. Fail terlibat

| Fail | Peranan |
|---|---|
| `scripts/tulis_nadi.py` | Penulis nadi (BAHARU — pembaikan utama) |
| `scripts/gateway_jalan.sh` | Pasang penulis nadi sebagai proses latar |
| `scripts/tampal_409.py` | Tampal `_rebuild_app_for_retry()` (pertahanan tambahan) |
| `.github/workflows/telegram.yml` | Jalankan tampalan selepas `pip install` |
| `.github/workflows/probe-serentak.yml` | Probe semasa bot hidup |
| `.github/workflows/probe-longpoll.yml` | Probe semasa bot mati |
| `home/config.yaml` | `drop_pending_on_cold_boot: true` |
| `boz-lab-node/telekey/standby.sh` | **Peserta konflik** (jangan biar nadi mati) |

---

## 8. PELAJARAN

1. **Jangan percaya label "Connected".** `getMe` 200 + log "Connected" hanya
   bermakna token sah, **bukan** bermakna polling berfungsi. Bukti sebenar ialah
   `getUpdates` pulang update.

2. **Cari pesaing merentas SEMUA repo, bukan hanya repo semasa.** Probe
   `probe-serentak` menyemak 4 repo tetapi terlepas pesaing kerana ia menyemak
   **status run**, bukan **pemegang token**. Pesaing berada dalam repo ke-5.

3. **Alat diagnostik boleh menjadi punca.** `getUpdates` bukan operasi baca
   pasif; ia mencipta sesi. Setiap probe menukar keadaan yang diperiksa.

4. **Reka bentuk separuh siap adalah perangkap.** `standby.sh` membaca nadi yang
   tiada siapa tulis. Sistem kelihatan berfungsi (nod ada, fail ada, logika ada)
   tetapi ia merosakkan perkara lain secara senyap. Semak **penulis** setiap
   isyarat yang dibaca, bukan hanya pembaca.

5. **Gelung abadi perlukan pemutus.** `ensure_cloud.sh` memulakan semula gateway
   setiap kali ia mati, tanpa sedar pesaing wujud. Penjaga yang buta terhadap
   punca sebenar akan mengekalkan kegagalan selama-lamanya.

---

