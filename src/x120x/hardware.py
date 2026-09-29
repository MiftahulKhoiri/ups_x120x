"""Akses hardware X120x: fuel gauge (I2C), sensor listrik mati (GPIO), kontrol charging.

Import smbus2/gpiozero dilakukan saat objek dibuat (lazy), supaya modul ini
tetap bisa di-import dan diuji di mesin non-Raspberry Pi.
"""
from __future__ import annotations

from typing import Optional

I2C_BUS = 1
FUEL_GAUGE_ADDR = 0x36  # IC fuel gauge (keluarga MAX17048)
REG_VCELL = 0x02        # register tegangan sel
REG_SOC = 0x04          # register state-of-charge (persen)
PLD_PIN = 6             # Power Loss Detection: HIGH = listrik AC normal
CHG_PIN = 16            # kontrol charging: pull-up = stop, pull-down = charge


def swap_bytes(raw: int) -> int:
    """SMBus membaca word little-endian, sedangkan IC mengirim big-endian."""
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def decode_voltage(raw: int) -> float:
    """Word mentah register VCELL -> volt (78.125 uV per LSB)."""
    return swap_bytes(raw) * 1.25 / 1000 / 16


def decode_capacity(raw: int) -> float:
    """Word mentah register SOC -> persen (1/256 % per LSB), dibatasi 0..100."""
    return max(0.0, min(100.0, swap_bytes(raw) / 256))


class FuelGauge:
    """Membaca tegangan dan kapasitas baterai lewat I2C."""

    def __init__(self, bus: int = I2C_BUS, address: int = FUEL_GAUGE_ADDR):
        import smbus2

        self._bus = smbus2.SMBus(bus)
        self._address = address

    def voltage(self) -> float:
        return decode_voltage(self._bus.read_word_data(self._address, REG_VCELL))

    def capacity(self) -> float:
        return decode_capacity(self._bus.read_word_data(self._address, REG_SOC))

    def close(self) -> None:
        self._bus.close()


class PowerLossDetector:
    """Pin PLD: LOW berarti adaptor/listrik AC bermasalah."""

    def __init__(self, pin: int = PLD_PIN):
        from gpiozero import Button

        self._pin = Button(pin)  # pull-up internal; "ditekan" = pin LOW

    @property
    def ac_ok(self) -> bool:
        return not self._pin.is_pressed

    def close(self) -> None:
        self._pin.close()


class ChargeControl:
    """Menyalakan/mematikan charging lewat konfigurasi pull pada GPIO 16.

    Device sengaja disimpan (tidak langsung dibuang) supaya konfigurasi pin
    tetap terpasang, dan ditutup dulu sebelum dibuat ulang agar tidak terjadi
    error "pin already in use". BELUM DIUJI di hardware asli.
    """

    def __init__(self, pin: int = CHG_PIN):
        self._pin_no = pin
        self._device = None
        self._enabled: Optional[bool] = None

    @property
    def enabled(self) -> Optional[bool]:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        if enabled == self._enabled:
            return
        from gpiozero import InputDevice

        if self._device is not None:
            self._device.close()
        self._device = InputDevice(self._pin_no, pull_up=not enabled)
        self._enabled = enabled

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None
