import json

from x120x import report
from x120x.monitor import Level, Snapshot
from x120x.rpi import SystemStats


def _snap(**kw):
    base = dict(timestamp=1.0, voltage=3.9, capacity=80.0, ac_ok=True, level=Level.AC_OK,
                charging=None, shutdown_pending=False, stats=None)
    base.update(kw)
    return Snapshot(**base)


def test_to_text_basic():
    text = report.to_text(_snap())
    assert "3.900 V" in text and "80.0 %" in text and "Listrik normal" in text
    assert "Raspberry Pi 5" not in text           # tanpa stats


def test_to_text_with_stats_and_pending_shutdown():
    stats = SystemStats(watts=4.5, temp_c=45.0, fan_rpm=3000)
    text = report.to_text(_snap(ac_ok=False, level=Level.SHUTDOWN, shutdown_pending=True, stats=stats))
    assert "shutdown sudah dijadwalkan" in text
    assert "Daya rail PMIC" in text and "4.50 W" in text and "3000 RPM" in text
    assert "TERPUTUS" in text


def test_to_dict_is_json_serializable():
    data = json.loads(json.dumps(report.to_dict(_snap(stats=SystemStats(temp_c=40.0)))))
    assert data["level"] == "ac_ok" and data["stats"]["temp_c"] == 40.0
