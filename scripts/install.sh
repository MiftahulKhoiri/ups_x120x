#!/usr/bin/env bash
# Memasang x120x-monitor sebagai service systemd (seluruh sistem).
# Pemakaian : sudo ./scripts/install.sh [--shutdown] [--prefix DIR]
#   --shutdown   service BENAR-BENAR mematikan Pi saat baterai habis (default: hanya log)
#   --prefix DIR lokasi venv (default /opt/x120x-monitor)
# DRY_RUN=1 hanya menampilkan perintah tanpa menjalankannya.
set -euo pipefail

PREFIX=/opt/x120x-monitor
SHUTDOWN=0
DRY="${DRY_RUN:-0}"

while [ $# -gt 0 ]; do
    case "$1" in
        --shutdown) SHUTDOWN=1 ;;
        --prefix)   PREFIX="${2:?--prefix butuh nilai}"; shift ;;
        -h|--help)  sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "Opsi tidak dikenal: $1" >&2; exit 2 ;;
    esac
    shift
done

run() { if [ "$DRY" = 1 ]; then echo "+ $*"; else "$@"; fi; }

if [ "$DRY" != 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "Jalankan dengan sudo: sudo $0 $*" >&2
    exit 1
fi

SRC="$(cd "$(dirname "$0")/.." && pwd)"
UNIT=/etc/systemd/system/x120x-monitor.service

run mkdir -p "$PREFIX"
run python3 -m venv --system-site-packages "$PREFIX/venv"
run "$PREFIX/venv/bin/pip" install "$SRC"
# pip membuat folder build sebagai root di dalam repo; bersihkan.
run rm -rf "$SRC/build" "$SRC"/src/*.egg-info

# Turunkan unit dari repo sesuai opsi.
tmp="$(mktemp)"
sed -e "s#/opt/x120x-monitor#$PREFIX#g" "$SRC/systemd/x120x-monitor.service" > "$tmp"
if [ "$SHUTDOWN" != 1 ]; then
    sed -i 's# --shutdown##' "$tmp"
fi
case "$PREFIX" in
    /home/*) sed -i 's/^ProtectHome=true/ProtectHome=read-only/' "$tmp" ;;  # venv di /home
esac
run install -m 644 "$tmp" "$UNIT"
rm -f "$tmp"

# Perintah `x120x` bisa dipanggil dari mana saja (venv ada di luar PATH).
run ln -sf "$PREFIX/venv/bin/x120x" /usr/local/bin/x120x

run systemctl daemon-reload
run systemctl enable x120x-monitor
run systemctl restart x120x-monitor   # restart agar kode/unit terbaru dipakai saat dipasang ulang

echo
if [ "$DRY" = 1 ]; then
    echo "(dry-run: tidak ada perintah yang dijalankan)"
    exit 0
fi
if [ "$SHUTDOWN" = 1 ]; then
    echo "Terpasang. Mode: SHUTDOWN AKTIF (Pi akan dimatikan saat baterai habis)."
else
    echo "Terpasang. Mode: hanya log (pasang ulang dengan --shutdown untuk mengaktifkan shutdown)."
fi
echo "Cek   : systemctl status x120x-monitor ; journalctl -u x120x-monitor -f"
echo "Status: x120x status"
