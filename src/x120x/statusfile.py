"""File status yang ditulis service `monitor`, supaya `x120x status` bisa dipakai
bersamaan dengan service tanpa bentrok pin PLD ("GPIO busy").

Penulisan atomik (file sementara + os.replace) agar pembaca tidak pernah melihat
file setengah jadi. Pembaca menganggap file kedaluwarsa jika terlalu tua,
misalnya service mati mendadak dan tidak sempat menghapusnya.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from .monitor import Level, Snapshot
from .report import to_dict
from .rpi import SystemStats

DEFAULT_STATUS_PATH = "/run/x120x/status.json"
DEFAULT_MAX_AGE_S = 60.0


def snapshot_from_dict(data: dict) -> Snapshot:
    """Kebalikan report.to_dict. KeyError/ValueError/TypeError jika bentuknya salah."""
    stats = data.get("stats")
    return Snapshot(
        timestamp=float(data["timestamp"]),
        voltage=float(data["voltage"]),
        capacity=float(data["capacity"]),
        ac_ok=bool(data["ac_ok"]),
        level=Level(data["level"]),
        charging=data["charging"],
        shutdown_pending=bool(data["shutdown_pending"]),
        stats=SystemStats(**stats) if stats else None,
    )


def write_status(snap: Snapshot, path: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(to_dict(snap)))
    os.chmod(tmp, 0o644)
    os.replace(tmp, target)


def read_status(path: str, max_age: float = DEFAULT_MAX_AGE_S,
                now: Optional[float] = None) -> Optional[Snapshot]:
    """Snapshot dari file, atau None jika tidak ada, rusak, atau sudah kedaluwarsa."""
    try:
        snap = snapshot_from_dict(json.loads(Path(path).read_text()))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    age = (time.time() if now is None else now) - snap.timestamp
    if age > max_age or age < -5:   # terlalu tua, atau jam mundur/tidak masuk akal
        return None
    return snap


def remove_status(path: str) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass
