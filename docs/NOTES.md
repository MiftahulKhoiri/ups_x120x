# Catatan hardware & temuan

## Peta hardware (X120x di Raspberry Pi 5)

| Fungsi | Detail |
|---|---|
| Fuel gauge | I2C bus 1, alamat `0x36` |
| Tegangan sel | register `0x02`, word big-endian, 78.125 µV/LSB |
| Kapasitas | register `0x04`, word big-endian, 1/256 % per LSB |
| Deteksi listrik mati (PLD) | GPIO 6, HIGH = normal, LOW = listrik/adaptor bermasalah |
| Kontrol charging | GPIO 16: pull-up = charging stop, pull-down = charging jalan |
| GPIO chip | `gpiochip0` di kernel >= 6.6.45 (sebelumnya `gpiochip4`); `gpiozero` + `lgpio` menanganinya |

## Temuan pada skrip SupTronics yang dipelajari

Ini alasan beberapa keputusan desain di proyek ini:

1. **Tiga API GPIO berbeda** (`gpiod` v1, `gpiod` v2, `gpiozero`) tercampur antar skrip.
   Di sini hanya `gpiozero`.
2. **Pembacaan gagal dianggap 0** (varian trixie): tegangan 0 V otomatis melewati
   ambang shutdown. Di sini error baca hanya dicatat.
3. **PID file basi**: proses yang crash meninggalkan `/var/run/X1200.pid` sehingga
   skrip menolak jalan lagi. Di sini tidak memakai PID file (systemd yang menjaga
   agar hanya satu instans).
4. **Hitungan kegagalan bertambah lebih dari sekali per siklus** sehingga
   "3 kegagalan berturut-turut" bisa tercapai dalam satu pembacaan. Di sini ada
   debounce sederhana: N sampel berturut-turut.
5. **Objek `InputDevice` baru dibuat tiap 30 detik** untuk pin charging tanpa
   ditutup dengan benar. Di sini satu objek dipakai ulang dan ditutup sebelum diganti.
6. **`shutdown` lewat `shell=True`**; di sini memakai daftar argumen.
7. Pengisian dihentikan tepat di 90% tanpa histeresis; di sini ada batas
   berhenti dan lanjut (default 90/85).

## Hasil review v0.2.0 (celah yang ditutup)

8. **Bacaan "aneh tapi tidak error" lolos** (celah di versi 0.1.0): word `0x0000`
   atau `0xFFFF` dari I2C bukan `OSError`, jadi terbaca 0 V / 5.12 V dan bisa
   memicu shutdown seperti temuan #2. Sekarang tegangan harus 2.5–4.5 V dan
   kapasitas `0xFFFF` ditolak (`SensorReadError`, subclass `OSError`).
9. **Sag tegangan sesaat** saat beban melonjak bisa langsung melewati
   `shutdown_voltage`. Sekarang kondisi shutdown harus bertahan `debounce` sampel.
10. **Listrik berkedip** membuat jadwal shutdown dijadwalkan-dibatalkan berulang.
    Sekarang pembatalan butuh `recovery_debounce` sampel "listrik normal".
11. **Gauge mati saat listrik mati** membuat monitor "buta": hanya log, baterai
    habis tanpa shutdown rapi. Sekarang setelah `max_sensor_errors` error berturut-turut
    dan PLD menunjukkan listrik mati, shutdown dijadwalkan (`Monitor.poll_blind`).
12. **Unit systemd restart tanpa henti** pada exit code 2 (I2C/GPIO bermasalah);
    sekarang `RestartPreventExitStatus=2` dan `StartLimitBurst`.
13. **"Daya sistem" menyesatkan**: nilainya jumlah V×A rail PMIC (sisi keluaran),
    bukan daya yang ditarik dari UPS. Label diganti "Daya rail PMIC".

## Belum diverifikasi

- `ChargeControl` (GPIO 16) ditulis mengikuti perilaku skrip asli tetapi belum diuji
  di hardware sungguhan. Perlu dicek bahwa konfigurasi pull bertahan selama objek
  `InputDevice` hidup, dan apa yang terjadi pada pin setelah proses berhenti
  (kontrol dilepas saat keluar).
- Terverifikasi di Pi (v0.2.0): `x120x status` saat `monitor` berjalan gagal dengan
  "GPIO busy" karena pin PLD diklaim eksklusif. Sejak v0.3.0 `status` membaca
  `/run/x120x/status.json` milik service; hanya `status --live` dan `gui` yang masih terkena.
- Opsi hardening systemd (`ProtectSystem=full`, `ProtectHome`, `PrivateTmp`)
  belum diuji dengan service sungguhan di Pi; periksa `journalctl -u x120x-monitor`
  setelah memasangnya.
- Pembacaan `vcgencmd pmic_read_adc` hanya ada di Raspberry Pi 5.
