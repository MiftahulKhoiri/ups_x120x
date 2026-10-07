# Changelog

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
