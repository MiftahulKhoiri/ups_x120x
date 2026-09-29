"""Statistik sistem Raspberry Pi 5 (PMIC, suhu, kipas)."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

# Contoh baris: "VDD_CORE_V volt(15)=0.87990000V" / "VDD_CORE_A current(7)=2.5A"
_PMIC_LINE = re.compile(
    r"^(?P<name>\S+)_(?P<kind>[AV])\s+\S+=(?P<value>-?\d+(?:\.\d+)?)[AV]\s*$"
)
FAN_DIR = Path("/sys/devices/platform/cooling_fan")
THERMAL_FILE = Path("/sys/class/thermal/thermal_zone0/temp")


@dataclass(frozen=True)
class SystemStats:
    input_voltage: Optional[float] = None
    core_voltage: Optional[float] = None
    core_amps: Optional[float] = None
    watts: Optional[float] = None
    temp_c: Optional[float] = None
    fan_rpm: Optional[int] = None


def _vcgencmd(*args: str) -> Optional[str]:
    try:
        done = subprocess.run(
            ["vcgencmd", *args], capture_output=True, text=True, timeout=5, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout


def parse_pmic(text: str) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Output `vcgencmd pmic_read_adc` -> (volts, amps), kunci = nama rail."""
    volts: Dict[str, float] = {}
    amps: Dict[str, float] = {}
    for line in text.splitlines():
        m = _PMIC_LINE.match(line.strip())
        if m:
            target = amps if m["kind"] == "A" else volts
            target[m["name"]] = float(m["value"])
    return volts, amps


def total_watts(volts: Dict[str, float], amps: Dict[str, float]) -> float:
    """Jumlah V x A untuk rail yang punya pasangan tegangan dan arus."""
    return sum(a * volts[name] for name, a in amps.items() if name in volts)


def cpu_temp() -> Optional[float]:
    out = _vcgencmd("measure_temp")
    if out:
        m = re.search(r"temp=(-?\d+(?:\.\d+)?)", out)
        if m:
            return float(m[1])
    try:
        return int(THERMAL_FILE.read_text()) / 1000
    except (OSError, ValueError):
        return None


def fan_rpm() -> Optional[int]:
    try:
        for path in FAN_DIR.rglob("fan1_input"):
            return int(path.read_text().strip())
    except (OSError, ValueError):
        pass
    return None


def read_system_stats() -> SystemStats:
    out = _vcgencmd("pmic_read_adc")
    volts, amps = parse_pmic(out) if out else ({}, {})
    return SystemStats(
        input_voltage=volts.get("EXT5V"),
        core_voltage=volts.get("VDD_CORE"),
        core_amps=amps.get("VDD_CORE"),
        watts=total_watts(volts, amps) if volts and amps else None,
        temp_c=cpu_temp(),
        fan_rpm=fan_rpm(),
    )
