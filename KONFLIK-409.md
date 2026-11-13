# KONFLIK 409 — PUNCA AKAR & PEMBAIKAN

**Tarikh:** 13 November 2026
**Gejala:** Bot Telegram kelihatan hidup tetapi **BISU** — semua mesej BOZ hilang.

---

## 1. Gejala sebenar

`gw_trace.log` menunjukkan urutan ini pada setiap run:

```
16:44:08  [Telegram] Connected to Telegram (polling mode)
16:44:10  SAMBUNG OK selepas 45s (bukti: baris 'Connected to Telegram')
16:44:12  [Telegram] Telegram polling conflict (1/5) — previous session still held open
16:44:38  [Telegram] Telegram polling conflict (2/5) — previous session still held open
16:45:15  [Telegram] Telegram polling conflict (3/5) — previous session still held open
          (sehingga 5/5, kemudian adapter PARKED)
```

Bot "hidup" — `getMe` pulang 200, log tulis "Connected to Telegram" — tetapi ia
**tidak menerima satu pun mesej** selama ~200 saat, kemudian mati. BOZ hantar
mesej, tiada balasan. Setiap kali bot dimulakan semula, kitaran yang sama.

---

## 2. Diagnostik — dua probe, bukan andaian

Hipotesis pertama ialah "ada proses lain memakai token yang sama". Diuji dengan
dua probe berbeza:

| Probe | Bila dijalankan | Keputusan |
|---|---|---|
| `probe-longpoll` | Bila bot **MATI** | `bebas=6, konflik=0` |
| `probe-serentak` | Bila bot **HIDUP** (4 minit) | `bebas=16, konflik=0` |

`probe-serentak` juga menyemak semua repo BOZ (`boz-cloud-runner`,
`boz-hermes-home`, `boz-bridge`, `boz-lab-node`) — **tiada run aktif** yang
memakai token.

**Kesimpulan: TIADA pesaing. Bot satu-satunya pemegang token.**

Namun konflik 409 tetap berlaku. Maka peserta konflik itu ialah **bot itu sendiri**.

---

## 3. Punca akar

Dalam `plugins/platforms/telegram/adapter.py`, fungsi
`_handle_polling_conflict()` memulihkan 409 dengan urutan berikut:

```python
await self._stop_updater_or_go_fatal(self._app, "conflict-retry")   # hentikan updater
await asyncio.sleep(RETRY_DELAY)                                    # tunggu 20s, 30s, seterusnya
await self._drain_polling_connections()                             # alirkan koneksi
app = self._app                                                     # APP YANG SAMA
await self._start_polling_once(app, drop_pending_updates=True)      # mula semula
```

**Masalahnya:** `app` ialah objek `Application` PTB **yang sama**. Kod Hermes
sendiri mengakui masalah ini dalam komennya:

> *"Without this, each retry starts a new getUpdates session that immediately
> gets 409'd by the previous one, creating the very conflict we are trying to
> recover from (#75017)."*

`drop_pending_updates=True` **tidak cukup**. PTB menyimpan koneksi `getUpdates`
di dalam `Application` (updater + bot + pool httpx). Menghentikan updater lalu
memulakannya semula pada objek yang sama boleh menggunakan semula pool itu,
sehingga sisa sesi lama di pelayan Telegram masih dikaitkan dengan kita.

Keputusan: setiap cubaan semula **mencipta konflik baharu yang ia cuba pulihkan**.

---

## 4. Pembaikan

`scripts/tampal_409.py` menanam kaedah baharu `_rebuild_app_for_retry()` yang
**membina semula `Application` PTB sepenuhnya** sebelum cubaan semula:

1. Hentikan updater pada app lama
2. `_shutdown_abandoned_app()` — lepaskan semua transport httpx
3. Bina `Application` **baharu** dengan tetapan sama seperti `connect()`
4. Daftar semula handler plugin + core (**wajib**, jika tidak bot terima mesej
   tetapi tiada sesiapa memprosesnya sehingga bisu)
5. `initialize()` + `start()` pada app baharu
6. Barulah `_start_polling_once(app_baharu, drop_pending_updates=True)`

Jika bina semula gagal, ia jatuh balik kepada app sedia ada — bot tidak mati
hanya kerana bina semula gagal.

---

## 5. Bukti tampalan berfungsi

Diuji pada salinan `adapter.py` sebenar (dari `git show HEAD`):

```
asal:    7380 baris, padanan _rebuild_app_for_retry = 0
tampal:  TAMPALAN BERJAYA
selepas: 7437 baris, padanan _rebuild_app_for_retry = 2
sahkan:  fail boleh diurai selepas tampalan (ast.parse)
idempotensi (jalan 2x): "sudah ada - diabaikan"
```

Tampalan dijalankan dalam workflow selepas `pip install`, kerana runner
meng-clone Hermes segar dari GitHub — suntingan laptop tidak terbawa.

---

## 6. Kenapa pembersihan sebelum ini GAGAL

Percubaan awal menambah `bersih_sesi_telegram()` dengan 20 x 15s probe
`getUpdates` (5 minit). Itu **memburukkan** keadaan:

> Setiap panggilan `getUpdates` yang **kita** buat mencipta sesi baharu di
> pelayan Telegram yang mengambil ~30 sampai 60 saat untuk luput. Gateway
> menyambung selepas itu, lalu di-409 oleh sesi yang **kita sendiri** baru cipta.

Kita menyebabkan konflik yang kita cuba baiki. Itulah sebabnya probe
`probe-serentak` penting — ia membuktikan tiada pesaing luar, jadi satu-satunya
pembersihan yang selamat ialah `deleteWebhook` + jeda, **tanpa** `getUpdates`.

---

## 7. Fail terlibat

| Fail | Peranan |
|---|---|
| `scripts/tampal_409.py` | Tampal `_rebuild_app_for_retry()` pada adapter runner |
| `scripts/gateway_jalan.sh` | Pembersihan: `deleteWebhook` sahaja + jeda, tanpa probe |
| `.github/workflows/telegram.yml` | Jalankan tampalan selepas `pip install` |
| `.github/workflows/probe-serentak.yml` | Probe semasa bot hidup (bukti tiada pesaing) |
| `.github/workflows/probe-longpoll.yml` | Probe semasa bot mati |
| `cloud/repo-home/config.yaml` | `drop_pending_on_cold_boot: true` |

---

## 8. Pelajaran untuk masa depan

1. **Jangan percaya label "Connected".** `getMe` 200 + log "Connected" hanya
   bermakna token sah, **bukan** bermakna polling berfungsi. Bukti sebenar ialah
   `getUpdates` pulang update.

2. **Probe mesti dijalankan pada saat masalah berlaku.** Probe semasa bot mati
   memberi keputusan palsu-negatif — ia tidak membuktikan apa-apa tentang saat
   gateway menyambung.

3. **Alat diagnostik boleh menjadi punca.** `getUpdates` bukan operasi baca
   pasif; ia mencipta sesi. Setiap probe menukar keadaan yang diperiksa.
