import json

import pytest

from x120x import cli
from x120x.rpi import SystemStats


class FakeGauge:
    def __init__(self):
        self.closed = False
        self.fail = False

    def voltage(self):
        if self.fail:
            raise OSError("i2c mati")
        return 3.9

    def capacity(self): return 80.0
    def close(self): self.closed = True


class FakePLD:
    ac_ok = True

    def __init__(self): self.closed = False
    def close(self): self.closed = True


@pytest.fixture(autouse=True)
def isolated_status_file(monkeypatch, tmp_path):
    """Jangan pernah menyentuh /run/x120x sungguhan saat test."""
    path = str(tmp_path / "status.json")
    monkeypatch.setattr(cli, "DEFAULT_STATUS_PATH", path)
    return path


@pytest.fixture
def hw(monkeypatch):
    gauge, pld = FakeGauge(), FakePLD()
    monkeypatch.setattr(cli, "_open_hardware", lambda: (gauge, pld))
    monkeypatch.setattr(cli, "read_system_stats", lambda: SystemStats(temp_c=40.0))
    return gauge, pld


def test_status_text_and_closes_hardware(hw, capsys):
    gauge, pld = hw
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "UPS X120x" in out and "80.0 %" in out
    assert gauge.closed and pld.closed


def test_status_json(hw, capsys):
    assert cli.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["capacity"] == 80.0 and data["level"] == "ac_ok"


def test_status_sensor_error_returns_1(hw, capsys):
    hw[0].fail = True
    assert cli.main(["status"]) == 1
    assert "Gagal membaca sensor" in capsys.readouterr().err
    assert hw[0].closed


@pytest.mark.parametrize("argv", [
    ["monitor", "--shutdown-pct", "40"],      # shutdown > critical
    ["monitor", "--debounce", "0"],
    ["monitor", "--charge-limit", "3"],       # resume = -2
    ["monitor", "--charge-limit", "120"],
    ["monitor", "--interval", "0"],
])
def test_invalid_arguments_exit_2(hw, argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2


def test_open_hardware_os_error(monkeypatch, capsys):
    def boom(): raise OSError("tidak ada i2c")
    monkeypatch.setattr(cli, "_open_hardware", boom)
    assert cli.main(["status"]) == 2
    assert "I2C" in capsys.readouterr().err


def test_open_hardware_pin_in_use_mentions_service(monkeypatch, capsys):
    def boom(): raise RuntimeError("GPIO busy")
    monkeypatch.setattr(cli, "_open_hardware", boom)
    assert cli.main(["status"]) == 2
    assert "service" in capsys.readouterr().err


def test_monitor_runs_with_json_output(hw, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda mon, interval, printer, stop: printer(mon.poll()))
    assert cli.main(["monitor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["capacity"] == 80.0


def test_monitor_closes_charge_control(hw, monkeypatch):
    class FakeCharge:
        enabled = None

        def __init__(self):
            self.calls, self.closed = [], False
            made.append(self)

        def set_enabled(self, value):
            self.calls.append(value)
            self.enabled = value

        def close(self): self.closed = True

    made = []
    monkeypatch.setattr("x120x.hardware.ChargeControl", FakeCharge)
    monkeypatch.setattr(cli, "run", lambda mon, interval, printer, stop: mon.poll())
    assert cli.main(["monitor", "--charge-limit", "90"]) == 0
    assert made[0].calls == [True] and made[0].closed


# --- file status service ---------------------------------------------------

def _fresh_status(path, **kw):
    import time
    from x120x.monitor import Level, Snapshot
    from x120x.statusfile import write_status
    base = dict(timestamp=time.time(), voltage=3.8, capacity=61.0, ac_ok=False, level=Level.ON_BATTERY,
                charging=None, shutdown_pending=False, stats=None)
    base.update(kw)
    write_status(Snapshot(**base), path)


def test_status_prefers_service_file_without_touching_hardware(isolated_status_file, monkeypatch, capsys):
    _fresh_status(isolated_status_file)

    def boom():
        raise AssertionError("hardware tidak boleh dibuka")

    monkeypatch.setattr(cli, "_open_hardware", boom)
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "61.0 %" in out and "dibaca dari service" in out


def test_status_json_from_service_is_pure_json(isolated_status_file, monkeypatch, capsys):
    _fresh_status(isolated_status_file)
    monkeypatch.setattr(cli, "_open_hardware", lambda: (_ for _ in ()).throw(AssertionError("jangan")))
    assert cli.main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["capacity"] == 61.0


def test_status_live_ignores_service_file(isolated_status_file, hw, capsys):
    _fresh_status(isolated_status_file)
    assert cli.main(["status", "--live"]) == 0
    out = capsys.readouterr().out
    assert "80.0 %" in out and "dibaca dari service" not in out


def test_status_falls_back_to_hardware_when_file_stale(isolated_status_file, hw, capsys):
    _fresh_status(isolated_status_file, timestamp=1.0)      # sangat tua
    assert cli.main(["status"]) == 0
    assert "80.0 %" in capsys.readouterr().out


def test_monitor_writes_status_file_and_removes_it_on_exit(isolated_status_file, hw, monkeypatch):
    import os
    seen = []

    def fake_run(mon, interval, publish, stop):
        publish(mon.poll())
        seen.append(os.path.exists(isolated_status_file))

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["monitor"]) == 0
    assert seen == [True]
    assert not os.path.exists(isolated_status_file)


def test_monitor_no_status_file(isolated_status_file, hw, monkeypatch):
    import os
    monkeypatch.setattr(cli, "run", lambda mon, interval, publish, stop: publish(mon.poll()))
    assert cli.main(["monitor", "--no-status-file"]) == 0
    assert not os.path.exists(isolated_status_file)


def test_monitor_survives_unwritable_status_path(hw, monkeypatch, tmp_path, capsys):
    blocker = tmp_path / "file_biasa"
    blocker.write_text("x")
    bad = str(blocker / "sub" / "status.json")       # induknya file biasa -> OSError
    monkeypatch.setattr(cli, "run", lambda mon, interval, publish, stop: publish(mon.poll()))
    assert cli.main(["monitor", "--status-file", bad]) == 0
    assert "UPS X120x" in capsys.readouterr().out      # tetap mencetak walau file status gagal ditulis
