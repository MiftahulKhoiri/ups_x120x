from x120x.monitor import (ChargePolicy, Level, Monitor, Thresholds, classify,
                           next_charge_state)


class FakeGauge:
    def __init__(self, capacity=80.0, voltage=3.9):
        self.c, self.v = capacity, voltage

    def capacity(self): return self.c
    def voltage(self): return self.v


class FakePLD:
    def __init__(self, ok=True): self.ac_ok = ok


class FakeShutdown:
    def __init__(self): self.calls = []
    def schedule(self, minutes): self.calls.append(("schedule", minutes))
    def cancel(self): self.calls.append(("cancel",))


T = Thresholds()


def test_classify_levels():
    assert classify(True, 5, 3.0, T) is Level.AC_OK
    assert classify(False, 80, 3.9, T) is Level.ON_BATTERY
    assert classify(False, 50, 3.9, T) is Level.LOW
    assert classify(False, 24, 3.9, T) is Level.CRITICAL
    assert classify(False, 15, 3.9, T) is Level.SHUTDOWN
    assert classify(False, 60, 3.1, T) is Level.SHUTDOWN  # tegangan terlalu rendah


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


def test_shutdown_scheduled_once_and_cancelled_on_restore():
    pld, sd = FakePLD(False), FakeShutdown()
    mon = Monitor(FakeGauge(10), pld, sd, Thresholds(debounce=1))
    mon.poll(); mon.poll()
    assert sd.calls == [("schedule", 5)]
    pld.ac_ok = True
    snap = mon.poll()
    assert snap.level is Level.AC_OK and not snap.shutdown_pending
    assert sd.calls[-1] == ("cancel",)


def test_no_shutdown_when_ac_ok_even_if_battery_low():
    sd = FakeShutdown()
    mon = Monitor(FakeGauge(5, 3.0), FakePLD(True), sd, Thresholds(debounce=1))
    assert mon.poll().level is Level.AC_OK
    assert sd.calls == []
