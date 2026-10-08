"""Antarmuka command line: `x120x status | monitor | gui`."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from typing import Optional, Sequence, Tuple

from . import __version__, report
from .monitor import ChargePolicy, Monitor, Thresholds, run
from .rpi import read_system_stats
from .shutdown import LogOnlyShutdown, SystemShutdown
from .statusfile import (DEFAULT_MAX_AGE_S, DEFAULT_STATUS_PATH, read_status,
                         remove_status, write_status)

log = logging.getLogger(__name__)


def _positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("harus lebih besar dari 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="x120x", description="Pemantau UPS HAT X120x untuk Raspberry Pi 5")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="tampilkan log detail")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="baca status sekali lalu keluar")
    s.add_argument("--json", action="store_true", help="keluaran JSON")
    s.add_argument("--live", action="store_true",
                   help="baca langsung dari hardware (abaikan file status service)")
    s.add_argument("--status-file", default=DEFAULT_STATUS_PATH,
                   help=f"file status yang ditulis service (default {DEFAULT_STATUS_PATH})")
    s.add_argument("--max-age", type=_positive_float, default=DEFAULT_MAX_AGE_S,
                   help="umur maksimum file status dalam detik (default 60)")

    m = sub.add_parser("monitor", help="pantau terus-menerus")
    m.add_argument("--interval", type=_positive_float, default=10.0, help="detik antar pembacaan (default 10)")
    m.add_argument("--shutdown", action="store_true",
                   help="BENAR-BENAR matikan sistem saat baterai habis (default: hanya log)")
    m.add_argument("--delay", type=int, default=5, help="menit tunda sebelum shutdown (default 5)")
    m.add_argument("--debounce", type=int, default=3,
                   help="sampel berturut-turut 'listrik mati'/'baterai rendah' sebelum dianggap nyata (default 3)")
    m.add_argument("--recovery-debounce", type=int, default=3,
                   help="sampel 'listrik normal' berturut-turut sebelum shutdown dibatalkan (default 3)")
    m.add_argument("--max-sensor-errors", type=int, default=6,
                   help="error baca gauge berturut-turut sebelum mode darurat (hanya PLD) aktif (default 6)")
    m.add_argument("--low", type=float, default=50.0)
    m.add_argument("--critical", type=float, default=25.0)
    m.add_argument("--shutdown-pct", type=float, default=15.0)
    m.add_argument("--shutdown-voltage", type=float, default=3.20)
    m.add_argument("--charge-limit", type=float, default=None, metavar="PERSEN",
                   help="stop charging di persen ini (eksperimental, belum diuji di hardware)")
    m.add_argument("--status-file", default=DEFAULT_STATUS_PATH,
                   help=f"tulis status terbaru ke file ini (default {DEFAULT_STATUS_PATH})")
    m.add_argument("--no-status-file", action="store_true", help="jangan tulis file status")
    m.add_argument("--json", action="store_true", help="satu baris JSON per pembacaan")

    g = sub.add_parser("gui", help="jendela status PyQt5 (butuh: pip install '.[gui]')")
    g.add_argument("--interval", type=_positive_float, default=30.0)
    return p


def _open_hardware():
    from .hardware import FuelGauge, PowerLossDetector

    gauge = FuelGauge()
    try:
        pld = PowerLossDetector()
    except Exception:
        gauge.close()
        raise
    return gauge, pld


def _build_monitor_config(args) -> Tuple[Thresholds, Optional[ChargePolicy]]:
    """Bangun ambang dan kebijakan charging; ValueError jika tidak valid."""
    thresholds = Thresholds(
        low_pct=args.low, critical_pct=args.critical, shutdown_pct=args.shutdown_pct,
        shutdown_voltage=args.shutdown_voltage, shutdown_delay_min=args.delay,
        debounce=args.debounce, recovery_debounce=args.recovery_debounce,
        max_sensor_errors=args.max_sensor_errors,
    )
    policy = None
    if args.charge_limit is not None:
        policy = ChargePolicy(args.charge_limit, args.charge_limit - 5)
    return thresholds, policy


def _instant_monitor(gauge, pld) -> Monitor:
    """Monitor sekali-baca untuk `status` dan `gui` (tanpa debounce, tanpa shutdown)."""
    return Monitor(gauge, pld, LogOnlyShutdown(), Thresholds(debounce=1, recovery_debounce=1),
                   stats_reader=read_system_stats)


def _print_status(args, snap) -> None:
    print(json.dumps(report.to_dict(snap), indent=2) if args.json else report.to_text(snap))


def _status_from_service(args) -> bool:
    """Tampilkan status dari file service jika masih segar. True jika berhasil."""
    snap = read_status(args.status_file, args.max_age)
    if snap is None:
        return False
    _print_status(args, snap)
    if not args.json:
        age = max(0.0, time.time() - snap.timestamp)
        print(f"(dibaca dari service, {age:.0f} detik lalu; pakai --live untuk baca langsung)")
    return True


def _cmd_status(args, gauge, pld) -> int:
    mon = _instant_monitor(gauge, pld)
    try:
        snap = mon.poll()
    except OSError as exc:
        print(f"Gagal membaca sensor: {exc}", file=sys.stderr)
        return 1
    _print_status(args, snap)
    return 0


def _make_publisher(path: Optional[str], printer):
    """Tulis file status (jika diminta) lalu cetak. Gagal menulis hanya dicatat sekali."""
    warned = []

    def publish(snap) -> None:
        if path:
            try:
                write_status(snap, path)
            except OSError as exc:
                if not warned:
                    warned.append(True)
                    log.warning("Gagal menulis file status %s: %s", path, exc)
        printer(snap)

    return publish


def _cmd_monitor(args, gauge, pld, thresholds: Thresholds, policy: Optional[ChargePolicy]) -> int:
    charge = None
    if policy is not None:
        from .hardware import ChargeControl

        charge = ChargeControl()
    action = SystemShutdown() if args.shutdown else LogOnlyShutdown()
    mon = Monitor(gauge, pld, action, thresholds, charge, policy, read_system_stats)

    status_path = None if args.no_status_file else args.status_file
    stop = threading.Event()
    handler = lambda *_: stop.set()  # noqa: E731
    old = {sig: signal.signal(sig, handler) for sig in (signal.SIGINT, signal.SIGTERM)}
    printer = ((lambda s: print(json.dumps(report.to_dict(s)), flush=True)) if args.json
               else (lambda s: print(report.to_text(s), flush=True)))
    try:
        run(mon, args.interval, _make_publisher(status_path, printer), stop)
    finally:
        for sig, previous in old.items():
            signal.signal(sig, previous)
        if status_path:
            remove_status(status_path)  # jangan tinggalkan status basi
        if charge is not None:
            charge.close()
            log.info("Kontrol charging dilepas")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    thresholds = policy = None
    if args.command == "monitor":
        try:
            thresholds, policy = _build_monitor_config(args)
        except ValueError as exc:
            parser.error(str(exc))

    # Service yang berjalan memegang pin PLD; ambil status dari file miliknya.
    if args.command == "status" and not args.live and _status_from_service(args):
        return 0

    try:
        gauge, pld = _open_hardware()
    except ImportError as exc:
        print(f"Dependensi belum terpasang ({exc.name}). Jalankan: pip install .", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Gagal membuka I2C/GPIO: {exc}\nPastikan I2C aktif (raspi-config) dan user ada di grup i2c/gpio.",
              file=sys.stderr)
        return 2
    except Exception as exc:  # mis. GPIOPinInUse dari gpiozero
        print(f"Gagal membuka GPIO: {exc}\n"
              "Jika service x120x-monitor sedang berjalan, pin PLD sedang dipakai olehnya.",
              file=sys.stderr)
        return 2

    try:
        if args.command == "status":
            return _cmd_status(args, gauge, pld)
        if args.command == "monitor":
            return _cmd_monitor(args, gauge, pld, thresholds, policy)
        if args.command == "gui":
            from .gui import run_gui

            return run_gui(_instant_monitor(gauge, pld), args.interval)
        return 1
    finally:
        for device in (pld, gauge):
            try:
                device.close()
            except Exception:
                log.debug("Gagal menutup perangkat", exc_info=True)
