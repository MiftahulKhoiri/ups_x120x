import sys
import types

import pytest

from x120x import rpi
from x120x.hardware import (FuelGauge, SensorReadError, decode_capacity,
                            decode_voltage, swap_bytes, validate_voltage)
from x120x.rpi import parse_pmic, total_watts

PMIC_SAMPLE = """\
   3V7_WL_SW_A current(0)=0.00600000A
   3V3_SYS_A current(1)=0.10000000A
   VDD_CORE_A current(15)=2.00000000A
   3V7_WL_SW_V volt(8)=3.70000000V
   3V3_SYS_V volt(9)=3.30000000V
   VDD_CORE_V volt(15)=0.90000000V
   EXT5V_V volt(24)=5.10000000V
"""


def _fake_smbus(monkeypatch, script):
    """Pasang modul smbus2 palsu; `script` = daftar nilai word atau Exception."""
    class FakeBus:
        def __init__(self, bus):
            self.script = list(script)

        def read_word_data(self, addr, reg):
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def close(self):
            pass

    module = types.ModuleType("smbus2")
    module.SMBus = FakeBus
    monkeypatch.setitem(sys.modules, "smbus2", module)
    monkeypatch.setattr("x120x.hardware.time.sleep", lambda s: None)


def test_swap_bytes():
    assert swap_bytes(0x3412) == 0x1234


def test_decode_voltage_full_cell():
    # 4.2 V -> 4.2 / (1.25/1000/16) = 53760 = 0xD200 (big-endian dari IC)
    assert abs(decode_voltage(swap_bytes(53760)) - 4.2) < 1e-6


def test_decode_capacity_and_clamp():
    assert decode_capacity(swap_bytes(50 * 256)) == 50.0
    assert decode_capacity(swap_bytes(120 * 256)) == 100.0


def test_validate_voltage_range():
    assert validate_voltage(3.7) == 3.7
    for bad in (0.0, 2.0, 5.12):
        with pytest.raises(SensorReadError):
            validate_voltage(bad)


def test_fuel_gauge_retries_then_succeeds(monkeypatch):
    _fake_smbus(monkeypatch, [OSError("noise"), swap_bytes(53760)])
    assert abs(FuelGauge().voltage() - 4.2) < 1e-6


def test_fuel_gauge_gives_up_after_retries(monkeypatch):
    _fake_smbus(monkeypatch, [OSError("a"), OSError("b"), OSError("c")])
    with pytest.raises(OSError):
        FuelGauge().voltage()


def test_fuel_gauge_rejects_glitch_words(monkeypatch):
    # 0x0000 dan 0xFFFF BUKAN baterai kosong: harus jadi error baca, bukan 0 V.
    _fake_smbus(monkeypatch, [0x0000, 0xFFFF, 0xFFFF])
    gauge = FuelGauge()
    with pytest.raises(SensorReadError):
        gauge.voltage()
    with pytest.raises(SensorReadError):
        gauge.voltage()
    with pytest.raises(SensorReadError):
        gauge.capacity()


def test_fuel_gauge_capacity_ok(monkeypatch):
    _fake_smbus(monkeypatch, [swap_bytes(50 * 256)])
    assert FuelGauge().capacity() == 50.0


def test_parse_pmic_and_watts():
    volts, amps = parse_pmic(PMIC_SAMPLE)
    assert volts["EXT5V"] == 5.1 and "EXT5V" not in amps
    assert amps["VDD_CORE"] == 2.0
    expected = 0.006 * 3.7 + 0.1 * 3.3 + 2.0 * 0.9
    assert abs(total_watts(volts, amps) - expected) < 1e-9


def test_cpu_temp_prefers_sysfs(monkeypatch, tmp_path):
    f = tmp_path / "temp"
    f.write_text("48500\n")
    monkeypatch.setattr(rpi, "THERMAL_FILE", f)
    monkeypatch.setattr(rpi, "_vcgencmd", lambda *a: pytest.fail("vcgencmd tidak boleh dipanggil"))
    assert rpi.cpu_temp() == 48.5


def test_cpu_temp_falls_back_to_vcgencmd(monkeypatch, tmp_path):
    monkeypatch.setattr(rpi, "THERMAL_FILE", tmp_path / "tidak_ada")
    monkeypatch.setattr(rpi, "_vcgencmd", lambda *a: "temp=51.2'C\n")
    assert rpi.cpu_temp() == 51.2
