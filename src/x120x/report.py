"""Format tampilan snapshot (teks dan dict/JSON)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Optional

from .monitor import Level, Snapshot

LEVEL_TEXT = {
    Level.AC_OK: "Listrik normal",
    Level.ON_BATTERY: "Memakai baterai UPS",
    Level.LOW: "Baterai menipis",
    Level.CRITICAL: "Baterai kritis!",
    Level.SHUTDOWN: "Baterai habis, sistem akan dimatikan!",
}


def _fmt(value: Optional[float], unit: str, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f} {unit}"


def to_dict(s: Snapshot) -> dict:
    return asdict(s)


def to_text(s: Snapshot) -> str:
    charging = {None: "-", True: "aktif", False: "berhenti"}[s.charging]
    lines = [
        "========== UPS X120x ==========",
        f"Tegangan baterai : {_fmt(s.voltage, 'V', 3)}",
        f"Kapasitas        : {_fmt(s.capacity, '%', 1)}",
        f"Pengisian        : {charging}",
        f"Listrik AC       : {'OK' if s.ac_ok else 'TERPUTUS / adaptor bermasalah'}",
        f"Status           : {LEVEL_TEXT[s.level]}",
    ]
    if s.shutdown_pending:
        lines.append("PERINGATAN       : shutdown sudah dijadwalkan")
    if s.stats is not None:
        st = s.stats
        lines += [
            "---------- Raspberry Pi 5 ----------",
            f"Input 5V         : {_fmt(st.input_voltage, 'V', 3)}",
            f"CPU core         : {_fmt(st.core_voltage, 'V', 3)} / {_fmt(st.core_amps, 'A', 3)}",
            f"Daya sistem      : {_fmt(st.watts, 'W')}",
            f"Suhu CPU         : {_fmt(st.temp_c, 'C', 1)}",
            f"Kipas            : {'-' if st.fan_rpm is None else f'{st.fan_rpm} RPM'}",
        ]
    lines.append("===============================")
    return "\n".join(lines)
