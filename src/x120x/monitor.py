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
    # Sampel berturut-turut "listrik mati" sebelum dianggap nyata. Dipakai juga
    # untuk memastikan kapasitas/tegangan rendah bukan sekadar sag sesaat.
    debounce: int = 3
    # Sampel berturut-turut "listrik normal" sebelum jadwal shutdown dibatalkan
    # (mencegah jadwal-batal bolak-balik saat listrik berkedip).
    recovery_debounce: int = 3
    # Error baca gauge berturut-turut sebelum beralih ke mode darurat (hanya PLD).
    max_sensor_errors: int = 6

    def __post_init__(self) -> None:
        if not 0 <= self.shutdown_pct < self.critical_pct < self.low_pct <= 100:
            raise ValueError("ambang harus berurutan: 0 <= shutdown < critical < low <= 100 (persen)")
        if not 2.5 <= self.shutdown_voltage <= 4.2:
            raise ValueError("shutdown_voltage harus di antara 2.5 dan 4.2 V")
        if self.shutdown_delay_min < 0:
            raise ValueError("shutdown_delay_min tidak boleh negatif")
        if self.debounce < 1 or self.recovery_debounce < 1:
            raise ValueError("debounce dan recovery_debounce minimal 1")
        if self.max_sensor_errors < 1:
            raise ValueError("max_sensor_errors minimal 1")


@dataclass(frozen=True)
class ChargePolicy:
    """Batasi pengisian supaya baterai awet. Histeresis mencegah bolak-balik."""
    stop_pct: float = 90.0
    resume_pct: float = 85.0

    def __post_init__(self) -> None:
        if not 0 < self.resume_pct < self.stop_pct <= 100:
            raise ValueError("batas charging harus memenuhi 0 < resume < stop <= 100")


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


def is_shutdown_condition(capacity: float, voltage: float, t: Thresholds) -> bool:
    return capacity <= t.shutdown_pct or voltage < t.shutdown_voltage


def classify(ac_ok: bool, capacity: float, voltage: float, t: Thresholds,
             allow_shutdown: bool = True) -> Level:
    if ac_ok:
        return Level.AC_OK
    if allow_shutdown and is_shutdown_condition(capacity, voltage, t):
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
        self._ok_streak = 0
        self._low_streak = 0
        self._ac_lost = False
        self._pending = False
        self._last_level: Optional[Level] = None

    @property
    def thresholds(self) -> Thresholds:
        return self._t

    def _update_ac(self, ac_raw: bool) -> bool:
        """Debounce dua arah. Mengembalikan True jika listrik dianggap normal."""
        t = self._t
        if ac_raw:
            self._ok_streak += 1
            self._loss_streak = 0
        else:
            self._loss_streak += 1
            self._ok_streak = 0
        if not self._ac_lost and self._loss_streak >= t.debounce:
            self._ac_lost = True
        elif self._ac_lost and self._ok_streak >= t.recovery_debounce:
            self._ac_lost = False
        return not self._ac_lost

    def poll(self) -> Snapshot:
        t = self._t
        voltage = self._gauge.voltage()
        capacity = self._gauge.capacity()
        ac_raw = self._pld.ac_ok

        ac_effective = self._update_ac(ac_raw)

        # Kondisi shutdown (kapasitas/tegangan rendah) harus bertahan beberapa
        # sampel berturut-turut, supaya sag sesaat karena beban tidak memicunya.
        if not ac_raw and is_shutdown_condition(capacity, voltage, t):
            self._low_streak += 1
        else:
            self._low_streak = 0
        confirmed = self._low_streak >= t.debounce
        level = classify(ac_effective, capacity, voltage, t, allow_shutdown=confirmed)

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

    def poll_blind(self) -> bool:
        """Mode darurat saat gauge gagal dibaca terus-menerus: hanya pakai pin PLD.

        Jika listrik terbukti mati (setelah debounce), shutdown dijadwalkan walau
        kapasitas baterai tidak diketahui; daripada baterai habis mendadak.
        Mengembalikan True jika shutdown sedang terjadwal.
        """
        ac_effective = self._update_ac(self._pld.ac_ok)
        if not ac_effective and not self._pending:
            log.error("Gauge tidak terbaca & listrik mati: menjadwalkan shutdown demi keamanan")
            self._apply_shutdown(Level.SHUTDOWN)
        elif ac_effective and self._pending:
            self._apply_shutdown(Level.AC_OK)
        return self._pending

    def _apply_shutdown(self, level: Level) -> None:
        if level is Level.SHUTDOWN and not self._pending:
            try:
                self._shutdown.schedule(self._t.shutdown_delay_min)
                self._pending = True
            except Exception:
                log.exception("Gagal menjadwalkan shutdown (akan dicoba lagi)")
        elif level is Level.AC_OK and self._pending:
            try:
                self._shutdown.cancel()
                self._pending = False
            except Exception:
                log.exception("Gagal membatalkan shutdown (akan dicoba lagi)")

    def _apply_charge(self, capacity: float) -> None:
        if self._charge is None or self._policy is None:
            return
        wanted = next_charge_state(self._charge.enabled, capacity, self._policy)
        try:
            self._charge.set_enabled(wanted)
        except Exception as exc:
            log.warning("Kontrol charging gagal: %s", exc)


def _handle_blind(monitor: Monitor, errors: int) -> None:
    if errors < monitor.thresholds.max_sensor_errors:
        return
    try:
        monitor.poll_blind()
    except Exception:
        log.exception("Mode darurat (hanya PLD) gagal")


def run(monitor: Monitor, interval: float, on_snapshot: Callable[[Snapshot], None],
        stop: Optional[threading.Event] = None) -> None:
    """Loop pemantauan.

    Error baca sensor dicatat dan TIDAK memicu shutdown. Hanya jika error berlanjut
    sebanyak `max_sensor_errors` kali DAN listrik terbukti mati, mode darurat
    (poll_blind) menjadwalkan shutdown. Exception tak terduga tidak mematikan loop.
    """
    stop = stop or threading.Event()
    errors = 0
    while not stop.is_set():
        try:
            snap = monitor.poll()
        except OSError as exc:
            errors += 1
            log.warning("Gagal membaca sensor (%d kali berturut-turut): %s", errors, exc)
            _handle_blind(monitor, errors)
        except Exception:
            errors += 1
            log.exception("Kesalahan tak terduga saat membaca status (%d kali berturut-turut)", errors)
            _handle_blind(monitor, errors)
        else:
            errors = 0
            try:
                on_snapshot(snap)
            except BrokenPipeError:
                log.error("Output ditutup; pemantauan dihentikan")
                break
            except Exception:
                log.exception("Gagal memproses snapshot")
        stop.wait(interval)
