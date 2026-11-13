#!/usr/bin/env python3
"""Tampal pembaikan konflik 409 pada adapter Telegram Hermes SELEPAS pemasangan.

KENAPA INI PERLU (bukti 13 Nov 2026, bukan andaian):

  Gateway menunjukkan 'polling conflict (1/5..5/5)' berulang sehingga adapter
  PARKED - bot kelihatan hidup ('Connected to Telegram'), getMe pulang 200,
  tetapi TIDAK menerima mesej selama 200s. Bot jadi bisu.

  Dua probe dijalankan untuk mencari pesaing:
    probe-serentak (bot HIDUP, 4 minit) : bebas=16, konflik=0
    probe-longpoll (bot MATI)           : bebas=6,  konflik=0
  Tiada proses lain memegang token. Maka peserta konflik ialah SESI KITA SENDIRI.

  Punca dalam kod Hermes: `_handle_polling_conflict()` menghentikan updater
  (`_stop_updater_or_go_fatal`), tidur, mengalirkan koneksi, kemudian memanggil
  `_start_polling_once(app, drop_pending_updates=True)` - pada APPLICATION YANG
  SAMA. PTB menyimpan koneksi getUpdates di dalam Application, jadi sisa sesi
  lama di pelayan Telegram masih dikaitkan dengan kita, lalu 409 lagi (1 sampai
  5), kemudian fatal, bot bisu.

  Pembaikan: bina semula Application PTB SEPENUHNYA sebelum cubaan semula, jadi
  koneksi getUpdates benar-benar baharu. Ditampal pada fail yang dipasang runner
  (runner clone Hermes segar dari GitHub, jadi suntingan laptop tidak terbawa).

Idempotent: jalan dua kali, tampalan kedua diabaikan.
"""
import glob
import io
import os
import sys

CALON = []


def cari_adapter():
    """Kembalikan laluan adapter.py, atau None.

    PENTING: calon relatif "hermes-agent/plugins/..." mesti disemak dengan
    os.path.abspath + kewujudan fail, kerana cwd boleh kebetulan mengandungi
    direktori hermes-agent (contoh: laptop BOZ) - itu bukan fail yang dipasang
    runner dan tampalan akan dilaporkan "sudah ada" secara PALSU.
    """
    akar = os.environ.get("HERMES_HOME", "")
    if akar:
        CALON.append(os.path.join(akar, "hermes-agent", "plugins", "platforms", "telegram", "adapter.py"))
        CALON.extend(glob.glob(os.path.join(akar, "installs", "*", "*", "hermes-agent", "plugins", "platforms", "telegram", "adapter.py")))
        CALON.extend(glob.glob(os.path.join(akar, "installs", "*", "hermes-agent", "plugins", "platforms", "telegram", "adapter.py")))
        CALON.extend(glob.glob(os.path.join(akar, "hermes-agent", "plugins", "platforms", "telegram", "adapter.py")))
    CALON.append("/tmp/ha/plugins/platforms/telegram/adapter.py")
    for p in CALON:
        if p and os.path.isfile(p):
            return p
    for akar_cari in ("/tmp", os.getcwd()):
        for dirpath, dirnames, filenames in os.walk(akar_cari):
            if "adapter.py" in filenames and dirpath.endswith(os.path.join("platforms", "telegram")):
                return os.path.join(dirpath, "adapter.py")
            if dirpath.count(os.sep) - akar_cari.count(os.sep) > 8:
                dirnames[:] = []
    return None


KAEDAH_BAHARU = '''    async def _rebuild_app_for_retry(self, app_lama):
        """Bina semula Application PTB sepenuhnya untuk cubaan semula selepas konflik 409.

        KENAPA (bukti probe 13 Nov 2026): probe-serentak semasa bot HIDUP pulang
        bebas=16, konflik=0 (4 minit); probe semasa bot MATI pulang bebas=6,
        konflik=0. Tiada pesaing. Konflik dalam log datang daripada SESI KITA
        SENDIRI: _handle_polling_conflict hanya menghentikan updater pada app yang
        SAMA lalu memulakannya semula; PTB menggunakan semula bot/pool yang sama
        sehingga sesi lama di pelayan Telegram masih dikaitkan dengan kita.

        Membina semula app memberi koneksi getUpdates yang benar-benar baharu.
        Kembalikan None bila gagal supaya pemanggil boleh jatuh balik (jangan mati).
        """
        app_baru = None
        try:
            try:
                if app_lama is not None and getattr(app_lama, "updater", None) is not None:
                    if getattr(app_lama.updater, "running", False):
                        await app_lama.updater.stop()
            except Exception:
                logger.debug("[%s] rebuild: updater.stop() gagal (abaikan)", self.name, exc_info=True)
            try:
                await _shutdown_abandoned_app(app_lama)
            except Exception:
                logger.debug("[%s] rebuild: shutdown app lama gagal (abaikan)", self.name, exc_info=True)

            from plugins.platforms.telegram.update_admission import TelegramApplication, build_update_processor
            builder = Application.builder().token(self.config.token)
            builder.application_class(TelegramApplication, {"adapter": self})
            custom_base_url = self.config.extra.get("base_url")
            if custom_base_url:
                builder = builder.base_url(custom_base_url)
                builder = builder.base_file_url(self.config.extra.get("base_file_url", custom_base_url))
            if self.config.extra.get("local_mode"):
                builder = builder.local_mode(True)
            request, get_updates_request = await self._build_ptb_requests()
            builder = builder.request(request).get_updates_request(get_updates_request)
            builder = builder.concurrent_updates(build_update_processor(self.config.extra, self.name))
            app_baru = builder.build()
            self._wire_plugin_handlers(app_baru)
            self._register_handlers(app_baru)
            self._app = app_baru
            self._bot = app_baru.bot
            await app_baru.initialize()
            await app_baru.start()
            logger.info("[%s] app dibina semula untuk cubaan konflik (koneksi getUpdates baharu)", self.name)
            return app_baru
        except Exception as err:
            logger.warning(
                "[%s] bina semula app gagal (%s) - jatuh balik kepada app sedia ada",
                self.name, _redact_telegram_error_text(err))
            return None

'''

PANGGILAN_LAMA = '''            self._polling_conflict_recovery_generation = expected_generation
            try:
                await self._start_polling_once(app, drop_pending_updates=True, error_callback=self._polling_error_callback_ref)'''

PANGGILAN_BAHARU = '''            self._polling_conflict_recovery_generation = expected_generation
            try:
                # TAMPALAN BOZ: bina semula app supaya koneksi getUpdates benar-benar baharu.
                app_baru = await self._rebuild_app_for_retry(app)
                if app_baru is not None:
                    app = app_baru
                await self._start_polling_once(app, drop_pending_updates=True, error_callback=self._polling_error_callback_ref)'''

JANGKAR_KAEDAH = '''    async def _handle_polling_conflict(self, error: Exception) -> None:'''


def tampal(laluan):
    asal = io.open(laluan, encoding="utf-8").read()
    if "_rebuild_app_for_retry" in asal:
        print("TAMPALAN: sudah ada - diabaikan")
        return True
    if JANGKAR_KAEDAH not in asal:
        print("TAMPALAN GAGAL: jangkar _handle_polling_conflict tidak dijumpai")
        return False
    if PANGGILAN_LAMA not in asal:
        print("TAMPALAN GAGAL: corak panggilan _start_polling_once tidak sepadan")
        return False

    baharu = asal.replace(JANGKAR_KAEDAH, KAEDAH_BAHARU + JANGKAR_KAEDAH, 1)
    baharu = baharu.replace(PANGGILAN_LAMA, PANGGILAN_BAHARU, 1)

    import ast
    try:
        ast.parse(baharu)
    except SyntaxError as e:
        print("TAMPALAN GAGAL: hasil tidak sah sintaks: %s" % e)
        return False

    io.open(laluan, "w", encoding="utf-8", newline="\n").write(baharu)
    print("TAMPALAN BERJAYA: %s" % laluan)
    return True


def main():
    laluan = cari_adapter()
    if not laluan:
        print("TAMPALAN GAGAL: adapter.py tidak dijumpai")
        for c in CALON:
            print("  calon: %s" % c)
        return 1
    print("adapter: %s" % laluan)
    ok = tampal(laluan)
    if ok:
        import ast
        try:
            ast.parse(io.open(laluan, encoding="utf-8").read())
            print("SAHKAN: fail boleh diurai selepas tampalan")
        except SyntaxError as e:
            print("SAHKAN GAGAL: %s" % e)
            return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
