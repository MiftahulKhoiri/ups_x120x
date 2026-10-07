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
