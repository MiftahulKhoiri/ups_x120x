import json
import os

from x120x.monitor import Level, Snapshot
from x120x.rpi import SystemStats
from x120x.statusfile import (read_status, remove_status, snapshot_from_dict,
                              write_status)
from x120x.report import to_dict


def _snap(ts=1000.0, **kw):
    base = dict(timestamp=ts, voltage=3.9, capacity=80.0, ac_ok=True, level=Level.AC_OK,
                charging=None, shutdown_pending=False, stats=SystemStats(temp_c=40.0, fan_rpm=3000))
    base.update(kw)
    return Snapshot(**base)


def test_roundtrip(tmp_path):
    path = str(tmp_path / "status.json")
    snap = _snap()
    write_status(snap, path)
    assert read_status(path, max_age=60, now=1010.0) == snap


def test_roundtrip_without_stats_and_other_level(tmp_path):
    path = str(tmp_path / "s.json")
    snap = _snap(stats=None, ac_ok=False, level=Level.SHUTDOWN, shutdown_pending=True, charging=True)
    write_status(snap, path)
    assert read_status(path, now=1001.0) == snap


def test_stale_file_is_ignored(tmp_path):
    path = str(tmp_path / "s.json")
    write_status(_snap(), path)
    assert read_status(path, max_age=60, now=1061.0) is None
    assert read_status(path, max_age=60, now=1059.0) is not None


def test_future_timestamp_is_ignored(tmp_path):
    path = str(tmp_path / "s.json")
    write_status(_snap(ts=5000.0), path)
    assert read_status(path, now=1000.0) is None


def test_missing_corrupt_and_wrong_shape(tmp_path):
    assert read_status(str(tmp_path / "tidak_ada.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{bukan json")
    assert read_status(str(bad)) is None
    bad.write_text(json.dumps({"timestamp": 1.0}))     # field kurang
    assert read_status(str(bad), now=1.0) is None
    data = to_dict(_snap())
    data["level"] = "level_aneh"
    bad.write_text(json.dumps(data))
    assert read_status(str(bad), now=1000.0) is None


def test_write_creates_parent_dir_is_atomic_and_readable(tmp_path):
    path = tmp_path / "run" / "x120x" / "status.json"
    write_status(_snap(), str(path))
    assert path.exists() and not (path.parent / "status.json.tmp").exists()
    assert (os.stat(path).st_mode & 0o777) == 0o644


def test_remove_status_is_quiet_when_missing(tmp_path):
    path = tmp_path / "s.json"
    write_status(_snap(), str(path))
    remove_status(str(path))
    assert not path.exists()
    remove_status(str(path))        # tidak error walau sudah tidak ada


def test_snapshot_from_dict_matches_to_dict():
    snap = _snap()
    assert snapshot_from_dict(to_dict(snap)) == snap
