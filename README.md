# x120x-monitor

Pemantau UPS HAT **X120x** (X1200 / X1201 / X1202) untuk **Raspberry Pi 5**:
baca tegangan & kapasitas baterai, deteksi listrik mati, jadwalkan shutdown
yang aman, dan tampilkan statistik sistem (daya, suhu, kipas).

> Proyek ini ditulis ulang dari nol dengan struktur sendiri, terinspirasi dari
> skrip-skrip resmi SupTronics: <https://github.com/suptronics/x120x>.
> Detail hardware (alamat I2C, pin GPIO) mengikuti dokumentasi HAT tersebut.

## Fitur

- `x120x status` — baca status sekali (teks atau `--json`)
- `x120x monitor` — pantau terus-menerus, dengan debounce dan shutdown terjadwal
- `x120x gui` — jendela status PyQt5 (opsional)
- Aman secara default: **tidak mematikan sistem** kecuali diberi `--shutdown`
- Error baca sensor (I2C) hanya dicatat, tidak pernah memicu shutdown
- Logika murni terpisah dari hardware, jadi bisa dites tanpa Raspberry Pi

## Instalasi (di Raspberry Pi 5)

```bash
sudo raspi-config nonint do_i2c 0        # aktifkan I2C
sudo apt install python3-venv python3-lgpio python3-pyqt5
python3 -m venv --system-site-packages venv
. venv/bin/activate
pip install .            # tambahkan '.[gui]' jika pip tidak memakai PyQt5 dari apt
```

## Pemakaian

```bash
x120x status
x120x status --json
x120x monitor --interval 10                 # hanya log (aman)
x120x monitor --shutdown --delay 5          # shutdown sungguhan
x120x monitor --charge-limit 90             # eksperimental: stop charging di 90%
x120x gui
```

Aturan default saat listrik mati (semua bisa diubah lewat opsi):

| Baterai | Status |
|---|---|
| > 50% | memakai baterai |
| 25–50% | menipis |
| 15–25% | kritis |
| ≤ 15% atau < 3.20 V | jadwalkan `shutdown -P +5`; dibatalkan otomatis jika listrik pulih |

## Jalankan sebagai service

Lihat `systemd/x120x-monitor.service`, lalu:

```bash
sudo cp systemd/x120x-monitor.service /etc/systemd/system/
sudo systemctl enable --now x120x-monitor
```

## Development

```bash
pip install -e '.[dev]'
pytest
```

Struktur:

```
src/x120x/
  hardware.py   # I2C fuel gauge, pin PLD, kontrol charging
  rpi.py        # vcgencmd/PMIC, suhu, kipas
  monitor.py    # logika: klasifikasi, debounce, histeresis, loop
  shutdown.py   # aksi shutdown (log-only / sistem)
  report.py     # format teks & JSON
  cli.py, gui.py
tests/
docs/NOTES.md   # catatan hardware & temuan dari skrip asli
```

## Ide pengembangan

- File konfigurasi (TOML) selain opsi CLI
- Notifikasi (Telegram/ntfy) saat listrik mati
- Ekspor metrik (Prometheus) & log riwayat baterai
- Uji dan finalisasi `--charge-limit` di hardware asli
- Integrasi shutdown yang menunggu proses penting (misal training/model server) selesai

## Lisensi

MIT (lihat `LICENSE`). Ganti nama pemegang hak cipta di file tersebut.
