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
- Bacaan sensor divalidasi (rentang tegangan, pola 0x0000/0xFFFF) dan I2C diulang
  otomatis; error baca hanya dicatat, tidak pernah langsung memicu shutdown
- Kapasitas/tegangan rendah harus bertahan beberapa sampel (tahan sag sesaat),
  dan pembatalan shutdown juga di-debounce (tahan listrik berkedip)
- Mode darurat: jika gauge mati total *dan* listrik terbukti mati (pin PLD),
  shutdown tetap dijadwalkan
- Logika murni terpisah dari hardware, jadi bisa dites tanpa Raspberry Pi

## Instalasi (di Raspberry Pi 5)

```bash
sudo raspi-config nonint do_i2c 0        # aktifkan I2C
sudo apt install python3-venv python3-lgpio python3-pyqt5
python3 -m venv --system-site-packages venv
. venv/bin/activate
pip install .            # tambahkan '.[gui]' jika pip tidak memakai PyQt5 dari apt
```

Butuh pip/setuptools yang cukup baru (build memakai `setuptools>=77`).

## Pemakaian

```bash
x120x status                                # pakai file status service bila ada
x120x status --live                         # paksa baca hardware langsung
x120x status --json
x120x monitor --interval 10                 # hanya log (aman)
x120x monitor --shutdown --delay 5          # shutdown sungguhan
x120x monitor --charge-limit 90             # eksperimental: stop charging di 90%
x120x gui
```

Opsi `monitor` yang berguna:

| Opsi | Default | Arti |
|---|---|---|
| `--debounce` | 3 | sampel berturut-turut "listrik mati"/"baterai rendah" sebelum dianggap nyata |
| `--recovery-debounce` | 3 | sampel "listrik normal" berturut-turut sebelum shutdown dibatalkan |
| `--max-sensor-errors` | 6 | error baca gauge berturut-turut sebelum mode darurat (hanya PLD) |
| `--low` / `--critical` | 50 / 25 | ambang persen (harus `shutdown < critical < low`) |
| `--shutdown-pct` / `--shutdown-voltage` | 15 / 3.20 | pemicu shutdown |
| `--delay` | 5 | menit tunda sebelum shutdown |

Aturan default saat listrik mati (semua bisa diubah lewat opsi):

| Baterai | Status |
|---|---|
| > 50% | memakai baterai |
| 25–50% | menipis |
| 15–25% | kritis |
| ≤ 15% atau < 3.20 V (bertahan 3 sampel) | jadwalkan `shutdown -P +5`; dibatalkan otomatis jika listrik pulih |

## Jalankan sebagai service

Lihat `systemd/x120x-monitor.service`. **Sesuaikan path `ExecStart`** dengan lokasi
venv kamu (default `/opt/x120x-monitor/venv`), lalu:

```bash
sudo cp systemd/x120x-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now x120x-monitor
```

Catatan: saat service berjalan, ia memegang pin PLD dan menulis status terbaru ke
`/run/x120x/status.json` (tiap siklus). `x120x status` otomatis membaca file itu bila
masih segar (< 60 detik), jadi aman dipakai bersamaan dengan service. `x120x status --live`
dan `x120x gui` membaca hardware langsung, sehingga gagal dengan "GPIO busy" selama service
berjalan; hentikan dulu (`sudo systemctl stop x120x-monitor`) jika memang butuh keduanya.
Matikan penulisan file status dengan `--no-status-file`.

## Development

```bash
pip install -e '.[dev]'
pytest
```

CI (GitHub Actions) menjalankan `pytest` di Python 3.9–3.13. Riwayat perubahan ada
di `CHANGELOG.md`.

Struktur:

```
src/x120x/
  hardware.py   # I2C fuel gauge (+validasi, retry), pin PLD, kontrol charging
  rpi.py        # vcgencmd/PMIC, suhu, kipas
  monitor.py    # logika: klasifikasi, debounce, histeresis, mode darurat, loop
  shutdown.py   # aksi shutdown (log-only / sistem)
  report.py     # format teks & JSON
  cli.py, gui.py
tests/
docs/NOTES.md   # catatan hardware & temuan dari skrip asli
```

## Ide pengembangan

- File konfigurasi (TOML) selain opsi CLI
- `x120x gui` yang ikut membaca file status service (saat ini masih membaca hardware langsung)
- Notifikasi (Telegram/ntfy) saat listrik mati
- Ekspor metrik (Prometheus) & log riwayat baterai
- Estimasi sisa waktu baterai (register CRATE fuel gauge)
- Uji dan finalisasi `--charge-limit` di hardware asli
- Integrasi shutdown yang menunggu proses penting (misal training/model server) selesai

## Lisensi

GPL-3.0 (lihat `LICENSE`).
