# Changelog

## 0.3.1

- `scripts/install.sh`: pemasang service systemd (venv di `/opt`, mode log-only secara
  default, `--shutdown` untuk mengaktifkan shutdown, `DRY_RUN=1` untuk simulasi).
- Diuji sebagai service systemd (mode user) di Raspberry Pi 5: start normal, file status
  `RuntimeDirectory` dibuat dan dihapus saat stop, restart otomatis setelah `kill -9`,
  exit code 2 tidak di-restart, exit code lain berhenti setelah `StartLimitBurst`.
- Dokumentasi: venv di `/home` butuh `ProtectHome=read-only`.

## 0.3.0

- `monitor` menulis status terbaru ke `/run/x120x/status.json` (atomik; opsi
  `--status-file` / `--no-status-file`) dan menghapusnya saat berhenti.
- `x120x status` membaca file itu bila masih segar (`--max-age`, default 60 detik), sehingga
  bisa dipakai bersamaan dengan service tanpa error "GPIO busy". `--live` memaksa baca hardware.
- Unit systemd: `RuntimeDirectory=x120x`.
- Diuji langsung di Raspberry Pi 5: status terbaca saat monitor jalan, file dihapus saat
  monitor dihentikan. Test: 73.

## 0.2.0

### Keamanan shutdown
- Bacaan fuel gauge divalidasi: tegangan di luar 2.5–4.5 V dan kapasitas `0xFFFF`
  ditolak sebagai error baca (sebelumnya bisa terbaca 0 V lalu memicu shutdown).
- Pembacaan I2C diulang hingga 3 kali sebelum dianggap gagal.
- Kapasitas/tegangan rendah harus bertahan `--debounce` sampel berturut-turut
  sebelum shutdown dijadwalkan (tahan terhadap sag sesaat karena beban).
- Debounce pemulihan listrik (`--recovery-debounce`): jadwal shutdown tidak
  bolak-balik dibatalkan saat listrik berkedip.
- Mode darurat: jika gauge gagal terbaca `--max-sensor-errors` kali berturut-turut
  DAN listrik terbukti mati (pin PLD), shutdown dijadwalkan.
- Gagal menjadwalkan/membatalkan shutdown dicoba lagi pada siklus berikutnya.
- Loop tidak lagi mati karena exception tak terduga; `BrokenPipeError` menghentikan
  loop dengan rapi.

### Ketahanan
- Validasi ambang & argumen (`shutdown < critical < low`, `--charge-limit`, `--interval > 0`).
- Hardware (gauge, PLD, kontrol charging) selalu ditutup saat keluar; handler sinyal dipulihkan.
- `ChargeControl` mereset statusnya jika pembuatan device gagal.
- Error GPIO dari gpiozero (mis. pin dipakai service lain) ditangani dengan pesan jelas.
- Perintah `shutdown` diberi timeout.

### Lainnya
- Unit systemd: tidak restart tanpa henti pada exit code 2, `After=local-fs.target`,
  hardening ringan.
- Suhu CPU dibaca dari sysfs lebih dulu (tanpa subprocess tambahan).
- Label "Daya sistem" diganti "Daya rail PMIC" (jumlah V×A rail PMIC, bukan daya input).
- Test bertambah dari 9 menjadi 58; ditambah GitHub Actions CI.
- `pyproject.toml`: versi dinamis dari `x120x.__version__`, lisensi SPDX, metadata.

## 0.1.0
- Rilis awal.
