# GERBANG BALASAN BOT — kenapa ia wujud & cara sahkan ia hidup

Ditulis 13 Nov 2026 selepas BOZ laporkan: *"bila saya mesej je telegram bot, ia
terus keluarkan link github, arahan, dan ayat panjang-panjang walaupun saya tak
suruh."*

## Punca sebenar (diukur, bukan tekaan)

| # | Punca | Ukuran |
|---|---|---|
| 1 | `channel_prompts` lama menyenaraikan **contoh arahan** untuk model tiru | 5,486 aksara, 1 pautan, **7 baris `python scripts`** |
| 2 | **Tiada apa-apa** memeriksa mesej KELUAR sebelum sampai Telegram | 0 penapis |

Model kecil membaca contoh (`bridge.py`, `fetch2.py`, `curl r.jina.ai`) sebagai
**jawapan yang dijangka**, lalu memuntahkannya walau BOZ hanya hantar "hi".

## Pembaikan — 2 lapis

### Lapis 1: prompt bersih (`prompt_bot.py`)
- 5,486 -> **4,039 aksara**
- **0 pautan**, **0 baris arahan terminal**
- 8 HUKUM, termasuk "HUKUM 0: panjang balasan ikut jenis mesej" (sapaan vs tugasan)
- Guna: `python scripts/prompt_bot.py --apply home/config.yaml`

### Lapis 2: gerbang mesej keluar (`balas_pantas.py` + `_boz_gerbang.py`)
Penapis ditanam **di dalam** `adapter.send()` dan `handle_message()` — bukan
membalut `Bot.send_message`, sebab laluan rich/draft tidak melalui PTB.

| Jenis mesej BOZ | Tindakan gerbang |
|---|---|
| Sapaan (`hi`, `ok`, `test`, `pagi`) | buang tutorial + pautan, had 6 baris / 600 aksara |
| Ringkas (<=4 perkataan, tiada kata kerja) | sama seperti sapaan |
| Tugasan (`cari`, `buat`, `upgrade`) | tutorial dibuang, **pautan DIKEKALKAN** (itu hasil kerja) |

Kalau semua kandungan dipotong, balasan gantian dipilih ikut mesej masuk
("Yo BOZ. Aku di sini — nak buat apa?" / "Hidup. Sambungan OK.") — bukan
template sama berulang.

Guna: `python scripts/pasang_gerbang.py --adapter <laluan adapter.py>`

## Jaminan keselamatan bot

1. **Idempotent** — jalankan 2x, penanda dikesan, tiada penanaman berganda.
2. **AST disahkan SEBELUM tulis** — kalau patch rosakkan sintaks, fail TIDAK ditulis.
3. **Gagal-lunak** — kalau modul penapis tiada, `tapis_keluar()` pulang teks ASAL.
   Bot tidak pernah mati kerana gerbang; ia hanya kehilangan penapis.
4. **Skop sempit** — hanya chat BOZ (`8043910371`). Pengguna lain tidak tersentuh.
5. **Tanpa rekod masuk = tanpa potongan** — kalau kita tidak tahu apa BOZ hantar,
   kita luluskan (jangan potong buta).
6. **Boleh dimatikan** — `BOZ_GERBANG_OFF=1` mematikan gerbang tanpa ubah kod.

## Sahkan ia hidup

```bash
python scripts/balas_pantas.py --uji          # 17/17 mesti lulus
```

Dalam konteks adapter sebenar (dijalankan oleh workflow):

```python
import _boz_gerbang as g
assert g._src_periksa is not None, "penapis TIDAK dimuat -> gerbang mati"
g.set_masuk("hi")
h = g.tapis_keluar("8043910371", "Berikut langkah:\n1. Pergi ke https://github.com/x/y")
assert "github" not in h and len(h) < 80
```

Workflow `telegram.yml` menjalankan kedua-dua ujian ini dalam langkah
**"GERBANG BALASAN + PROMPT BERSIH"**, dan ia **GAGAL KERAS** kalau tidak lulus —
jadi gerbang mati tidak boleh berlaku senyap.

## Pepijat yang sudah ditemui & dibaiki

| Pepijat | Punca | Baiki |
|---|---|---|
| Serpihan `lik Settings` | `re.sub()` potong tengah baris | `_buang_baris_tutorial()` buang baris penuh |
| `Berikut langkah:` terselamat | corak perlukan `(adalah\|ialah)` | corak terima `berikut\s*:` |
| Arahan terminal terselamat | tiada corak untuk `curl`/`npm` | corak `^\s*(curl\|wget\|npm\|...)` |
| `FileNotFoundError` di Windows | `find` pulang `/c/Users/...` | `_normalisasi()` tukar ke `C:/Users/...` |

## SEJARAH: jangan ulang silap ini

- **JANGAN** `sed` pada `config.yaml` — sejarah: config 4,458 bait jadi 45 bait.
  Guna `prompt_bot.py --apply` (parser YAML + sahkan).
- **JANGAN** teka corak adapter — jalankan pemasang, ia cetak corak sebenar kalau
  tidak padan.
- **JANGAN** percaya "push berjaya" — sahkan fail di GitHub (200 + saiz).
