"""Logika pemantauan UPS. Tidak menyentuh hardware langsung, jadi mudah diuji."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from .rpi import SystemStats

log = logging.getLogger(__name__)


class Level(str, Enum):
    AC_OK = "ac_ok"            # listrik normal
    ON_BATTERY = "on_battery"  # listrik mati, baterai masih banyak
    LOW = "low"                # baterai mulai menipis
    CRITICAL = "critical"      # baterai kritis
    SHUTDOWN = "shutdown"      # saatnya mematikan sistem


@dataclass(frozen=True)
class Thresholds:
    low_pct: float = 50.0
    critical_pct: float = 25.0
    shutdown_pct: float = 15.0
    shutdown_voltage: float = 3.20
    shutdown_delay_min: int = 5
    debounce: int = 3  # sampel berturut-turut "listrik mati" sebelum dianggap nyata


@dataclass(frozen=True)
class ChargePolicy:
    """Batasi pengisian supaya baterai awet. Histeresis mencegah bolak-balik."""
    stop_pct: float = 90.0
    resume_pct: float = 85.0


@dataclass(frozen=True)
class Snapshot:
    timestamp: float
    voltage: float
    capacity: float
    ac_ok: bool                 # pembacaan mentah pin PLD
    level: Level                # sudah melalui debounce
    charging: Optional[bool]    # None = kontrol charging tidak dipakai
    shutdown_pending: bool
    stats: Optional[SystemStats] = None


def classify(ac_ok: bool, capacity: float, voltage: float, t: Thresholds) -> Level:
    if ac_ok:
        return Level.AC_OK
    if capacity <= t.shutdown_pct or voltage < t.shutdown_voltage:
        return Level.SHUTDOWN
    if capacity < t.critical_pct:
        return Level.CRITICAL
    if capacity <= t.low_pct:
        return Level.LOW
    return Level.ON_BATTERY


def next_charge_state(current: Optional[bool], capacity: float, p: ChargePolicy) -> bool:
    if capacity >= p.stop_pct:
        return False
    if capacity < p.resume_pct:
        return True
    return True if current is None else current


class Monitor:
    """Membaca sensor, menentukan level, lalu menjalankan aksi.

    gauge  : objek dengan .voltage() dan .capacity()
    pld    : objek dengan properti .ac_ok
    shutdown : objek dengan .schedule(menit) dan .cancel()
    charge : (opsional) objek dengan .enabled dan .set_enabled(bool)
    """

    def __init__(self, gauge, pld, shutdown, thresholds: Thresholds = Thresholds(),
                 charge=None, charge_policy: Optional[ChargePolicy] = None,
                 stats_reader: Optional[Callable[[], SystemStats]] = None):
        self._gauge = gauge
        self._pld = pld
        self._shutdown = shutdown
        self._t = thresholds
        self._charge = charge
        self._policy = charge_policy
        self._stats_reader = stats_reader
        self._loss_streak = 0
        self._pending = False
        self._last_level: Optional[Level] = None

    def poll(self) -> Snapshot:
        t = self._t
        voltage = self._gauge.voltage()
        capacity = self._gauge.capacity()
        ac_raw = self._pld.ac_ok

        self._loss_streak = 0 if ac_raw else self._loss_streak + 1
        ac_effective = self._loss_streak < max(1, t.debounce)
        level = classify(ac_effective, capacity, voltage, t)

        self._apply_shutdown(level)
        self._apply_charge(capacity)

        if level is not self._last_level:
            log.info("Status: %s (baterai %.1f%%, %.3f V)", level.value, capacity, voltage)
            self._last_level = level

        return Snapshot(
            timestamp=time.time(), voltage=voltage, capacity=capacity, ac_ok=ac_raw,
            level=level, charging=self._charge.enabled if self._charge else None,
            shutdown_pending=self._pending,
            stats=self._stats_reader() if self._stats_reader else None,
        )

    def _apply_shutdown(self, level: Level) -> None:
        if level is Level.SHUTDOWN and not self._pending:
            try:
                self._shutdown.schedule(self._t.shutdown_delay_min)
                self._pending = True
            except Exception:
                log.exception("Gagal menjadwalkan shutdown")
        elif level is Level.AC_OK and self._pending:
            self._shutdown.cancel()
            self._pending = False

    def _apply_charge(self, capacity: float) -> None:
        if self._charge is None or self._policy is None:
            return
        wanted = next_charge_state(self._charge.enabled, capacity, self._policy)
        try:
            self._charge.set_enabled(wanted)
        except Exception as exc:
            log.warning("Kontrol charging gagal: %s", exc)


def run(monitor: Monitor, interval: float, on_snapshot: Callable[[Snapshot], None],
        stop: Optional[threading.Event] = None) -> None:
    """Loop pemantauan. Error baca sensor hanya dicatat, TIDAK memicu shutdown."""
    stop = stop or threading.Event()
    errors = 0
    while not stop.is_set():
        try:
            on_snapshot(monitor.poll())
            errors = 0
        except OSError as exc:
            errors += 1
            log.warning("Gagal membaca sensor (%d kali berturut-turut): %s", errors, exc)
        stop.wait(interval)
