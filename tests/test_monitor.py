import pytest

from x120x.monitor import (ChargePolicy, Level, Monitor, Thresholds, classify,
                           next_charge_state, run)


class FakeGauge:
    def __init__(self, capacity=80.0, voltage=3.9):
        self.c, self.v = capacity, voltage

    def capacity(self): return self.c
    def voltage(self): return self.v


class DeadGauge:
    def capacity(self): raise OSError("i2c mati")
    def voltage(self): raise OSError("i2c mati")


class OnceBrokenGauge(FakeGauge):
    def __init__(self):
        super().__init__()
        self.broken = True

    def voltage(self):
        if self.broken:
            self.broken = False
            raise ValueError("aneh")
        return self.v


class FakePLD:
    def __init__(self, ok=True): self.ac_ok = ok


class FakeShutdown:
    def __init__(self): self.calls = []
    def schedule(self, minutes): self.calls.append(("schedule", minutes))
    def cancel(self): self.calls.append(("cancel",))


class FlakyShutdown(FakeShutdown):
    def __init__(self):
        super().__init__()
        self.fail = True

    def schedule(self, minutes):
        if self.fail:
            self.fail = False
            raise RuntimeError("sudo gagal")
        super().schedule(minutes)


class CancelFails(FakeShutdown):
    def cancel(self): raise RuntimeError("gagal batal")


class LoopStop:
    """Pengganti threading.Event: loop berjalan tepat `loops` kali, tanpa menunggu."""
    def __init__(self, loops):
        self.loops = loops

    def is_set(self):
        self.loops -= 1
        return self.loops < 0

    def wait(self, _): pass


T = Thresholds()


def test_classify_levels():
    assert classify(True, 5, 3.0, T) is Level.AC_OK
    assert classify(False, 80, 3.9, T) is Level.ON_BATTERY
    assert classify(False, 50, 3.9, T) is Level.LOW
    assert classify(False, 24, 3.9, T) is Level.CRITICAL
    assert classify(False, 15, 3.9, T) is Level.SHUTDOWN
    assert classify(False, 60, 3.1, T) is Level.SHUTDOWN  # tegangan terlalu rendah
    assert classify(False, 60, 3.1, T, allow_shutdown=False) is Level.ON_BATTERY


@pytest.mark.parametrize("kwargs", [
    dict(shutdown_pct=30), dict(low_pct=120), dict(debounce=0), dict(recovery_debounce=0),
    dict(shutdown_voltage=1.0), dict(shutdown_delay_min=-1), dict(max_sensor_errors=0),
])
def test_thresholds_invalid(kwargs):
    with pytest.raises(ValueError):
        Thresholds(**kwargs)


@pytest.mark.parametrize("stop,resume", [(90, 95), (101, 90), (5, 0), (50, 50)])
def test_charge_policy_invalid(stop, resume):
    with pytest.raises(ValueError):
        ChargePolicy(stop, resume)


def test_charge_hysteresis():
    p = ChargePolicy(90, 85)
    assert next_charge_state(None, 50, p) is True
    assert next_charge_state(True, 90, p) is False
    assert next_charge_state(False, 87, p) is False  # di zona histeresis, tetap
    assert next_charge_state(False, 84, p) is True


def test_debounce_delays_power_loss():
    pld, sd = FakePLD(False), FakeShutdown()
    mon = Monitor(FakeGauge(10), pld, sd, Thresholds(debounce=3))
    assert mon.poll().level is Level.AC_OK
    assert mon.poll().level is Level.AC_OK
    assert mon.poll().level is Level.SHUTDOWN
    assert sd.calls == [("schedule", 5)]


def test_voltage_sag_does_not_trigger_shutdown():
    gauge, pld, sd = FakeGauge(60, 3.9), FakePLD(False), FakeShutdown()
    mon = Monitor(gauge, pld, sd, Thresholds(debounce=3))
    mon.poll(); mon.poll()
    gauge.v = 3.1                                   # sag sesaat karena beban
    assert mon.poll().level is Level.ON_BATTERY
    gauge.v = 3.9
    mon.poll()                                      # pulih -> hitungan direset
    gauge.v = 3.1                                   # kali ini bertahan
    mon.poll(); mon.poll()
    assert sd.calls == []
    assert mon.poll().level is Level.SHUTDOWN
    assert sd.calls == [("schedule", 5)]


def test_shutdown_scheduled_once_and_cancelled_on_restore():
    pld, sd = FakePLD(False), FakeShutdown()
    mon = Monitor(FakeGauge(10), pld, sd, Thresholds(debounce=1, recovery_debounce=1))
    mon.poll(); mon.poll()
    assert sd.calls == [("schedule", 5)]
    pld.ac_ok = True
    snap = mon.poll()
    assert snap.level is Level.AC_OK and not snap.shutdown_pending
    assert sd.calls[-1] == ("cancel",)


def test_recovery_debounce_avoids_flapping():
    pld, sd = FakePLD(False), FakeShutdown()
    mon = Monitor(FakeGauge(10), pld, sd, Thresholds(debounce=1, recovery_debounce=3))
    mon.poll()
    pld.ac_ok = True
    assert mon.poll().level is not Level.AC_OK
    assert mon.poll().level is not Level.AC_OK
    assert sd.calls == [("schedule", 5)]            # belum dibatalkan
    snap = mon.poll()
    assert snap.level is Level.AC_OK and not snap.shutdown_pending
    assert sd.calls[-1] == ("cancel",)


def test_no_shutdown_when_ac_ok_even_if_battery_low():
    sd = FakeShutdown()
    mon = Monitor(FakeGauge(5, 3.0), FakePLD(True), sd, Thresholds(debounce=1))
    assert mon.poll().level is Level.AC_OK
    assert sd.calls == []


def test_schedule_failure_is_retried():
    sd = FlakyShutdown()
    mon = Monitor(FakeGauge(10), FakePLD(False), sd, Thresholds(debounce=1))
    assert mon.poll().shutdown_pending is False
    assert mon.poll().shutdown_pending is True
    assert sd.calls == [("schedule", 5)]


def test_cancel_failure_keeps_pending():
    pld = FakePLD(False)
    mon = Monitor(FakeGauge(10), pld, CancelFails(), Thresholds(debounce=1, recovery_debounce=1))
    assert mon.poll().shutdown_pending is True
    pld.ac_ok = True
    assert mon.poll().shutdown_pending is True      # akan dicoba lagi


def test_poll_blind_schedules_and_cancels():
    pld, sd = FakePLD(False), FakeShutdown()
    mon = Monitor(DeadGauge(), pld, sd, Thresholds(debounce=2, recovery_debounce=1))
    assert mon.poll_blind() is False
    assert mon.poll_blind() is True
    assert sd.calls == [("schedule", 5)]
    pld.ac_ok = True
    assert mon.poll_blind() is False
    assert sd.calls[-1] == ("cancel",)


def test_run_sensor_errors_never_shutdown_when_ac_ok():
    sd = FakeShutdown()
    mon = Monitor(DeadGauge(), FakePLD(True), sd, Thresholds(max_sensor_errors=2))
    got = []
    run(mon, 0, got.append, LoopStop(6))
    assert got == [] and sd.calls == []


def test_run_dead_gauge_and_ac_lost_escalates_once():
    sd = FakeShutdown()
    t = Thresholds(debounce=1, recovery_debounce=1, max_sensor_errors=2)
    mon = Monitor(DeadGauge(), FakePLD(False), sd, t)
    run(mon, 0, lambda s: None, LoopStop(6))
    assert sd.calls == [("schedule", 5)]


def test_run_survives_unexpected_exception():
    got = []
    run(Monitor(OnceBrokenGauge(), FakePLD(True), FakeShutdown()), 0, got.append, LoopStop(3))
    assert len(got) == 2


def test_run_stops_on_broken_pipe():
    calls = []

    def boom(_):
        calls.append(1)
        raise BrokenPipeError

    run(Monitor(FakeGauge(), FakePLD(True), FakeShutdown()), 0, boom, LoopStop(10))
    assert len(calls) == 1
