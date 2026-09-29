from x120x.hardware import decode_capacity, decode_voltage, swap_bytes
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


def test_swap_bytes():
    assert swap_bytes(0x3412) == 0x1234


def test_decode_voltage_full_cell():
    # 4.2 V -> 4.2 / (1.25/1000/16) = 53760 = 0xD200 (big-endian dari IC)
    assert abs(decode_voltage(swap_bytes(53760)) - 4.2) < 1e-6


def test_decode_capacity_and_clamp():
    assert decode_capacity(swap_bytes(50 * 256)) == 50.0
    assert decode_capacity(swap_bytes(120 * 256)) == 100.0


def test_parse_pmic_and_watts():
    volts, amps = parse_pmic(PMIC_SAMPLE)
    assert volts["EXT5V"] == 5.1 and "EXT5V" not in amps
    assert amps["VDD_CORE"] == 2.0
    expected = 0.006 * 3.7 + 0.1 * 3.3 + 2.0 * 0.9
    assert abs(total_watts(volts, amps) - expected) < 1e-9
