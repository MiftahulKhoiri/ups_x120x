"""Antarmuka command line: `x120x status | monitor | gui`."""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from typing import Optional, Sequence

from . import __version__, report
from .monitor import ChargePolicy, Monitor, Thresholds, run
from .rpi import read_system_stats
from .shutdown import LogOnlyShutdown, SystemShutdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="x120x", description="Pemantau UPS HAT X120x untuk Raspberry Pi 5")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="tampilkan log detail")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="baca status sekali lalu keluar")
    s.add_argument("--json", action="store_true", help="keluaran JSON")

    m = sub.add_parser("monitor", help="pantau terus-menerus")
    m.add_argument("--interval", type=float, default=10.0, help="detik antar pembacaan (default 10)")
    m.add_argument("--shutdown", action="store_true",
                   help="BENAR-BENAR matikan sistem saat baterai habis (default: hanya log)")
    m.add_argument("--delay", type=int, default=5, help="menit tunda sebelum shutdown (default 5)")
    m.add_argument("--debounce", type=int, default=3, help="sampel 'listrik mati' berturut-turut (default 3)")
    m.add_argument("--low", type=float, default=50.0)
    m.add_argument("--critical", type=float, default=25.0)
    m.add_argument("--shutdown-pct", type=float, default=15.0)
    m.add_argument("--shutdown-voltage", type=float, default=3.20)
    m.add_argument("--charge-limit", type=float, default=None, metavar="PERSEN",
                   help="stop charging di persen ini (eksperimental, belum diuji di hardware)")
    m.add_argument("--json", action="store_true", help="satu baris JSON per pembacaan")

    g = sub.add_parser("gui", help="jendela status PyQt5 (butuh: pip install '.[gui]')")
    g.add_argument("--interval", type=float, default=30.0)
    return p


def _open_hardware():
    from .hardware import FuelGauge, PowerLossDetector

    return FuelGauge(), PowerLossDetector()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        gauge, pld = _open_hardware()
    except ImportError as exc:
        print(f"Dependensi belum terpasang ({exc.name}). Jalankan: pip install .", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Gagal membuka I2C/GPIO: {exc}\nPastikan I2C aktif (raspi-config) dan user ada di grup i2c/gpio.",
              file=sys.stderr)
        return 2

    if args.command == "status":
        mon = Monitor(gauge, pld, LogOnlyShutdown(), Thresholds(debounce=1), stats_reader=read_system_stats)
        snap = mon.poll()
        print(json.dumps(report.to_dict(snap), indent=2) if args.json else report.to_text(snap))
        return 0

    if args.command == "monitor":
        thresholds = Thresholds(args.low, args.critical, args.shutdown_pct,
                                args.shutdown_voltage, args.delay, args.debounce)
        charge = policy = None
        if args.charge_limit is not None:
            from .hardware import ChargeControl

            charge = ChargeControl()
            policy = ChargePolicy(args.charge_limit, args.charge_limit - 5)
        action = SystemShutdown() if args.shutdown else LogOnlyShutdown()
        mon = Monitor(gauge, pld, action, thresholds, charge, policy, read_system_stats)

        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        printer = ((lambda s: print(json.dumps(report.to_dict(s)), flush=True)) if args.json
                   else (lambda s: print(report.to_text(s), flush=True)))
        run(mon, args.interval, printer, stop)
        return 0

    if args.command == "gui":
        from .gui import run_gui

        mon = Monitor(gauge, pld, LogOnlyShutdown(), Thresholds(debounce=1), stats_reader=read_system_stats)
        return run_gui(mon, args.interval)
    return 1
