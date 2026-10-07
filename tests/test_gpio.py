import sys
import types

import pytest

from x120x.hardware import ChargeControl, PowerLossDetector


@pytest.fixture
def fake_gpiozero(monkeypatch):
    """Pasang modul gpiozero palsu; mengembalikan daftar device yang dibuat."""
    class Created(list):
        fake_input = None

    created = Created()

    class FakeInput:
        fail = False

        def __init__(self, pin, pull_up=None):
            if FakeInput.fail:
                raise RuntimeError("pin sibuk")
            self.pin, self.pull_up, self.closed = pin, pull_up, False
            created.append(self)

        def close(self):
            self.closed = True

    class FakeButton(FakeInput):
        def __init__(self, pin):
            super().__init__(pin)
            self.is_pressed = False

    module = types.ModuleType("gpiozero")
    module.InputDevice, module.Button = FakeInput, FakeButton
    monkeypatch.setitem(sys.modules, "gpiozero", module)
    FakeInput.fail = False
    created.fake_input = FakeInput
    return created


def test_pld_pressed_means_ac_lost(fake_gpiozero):
    pld = PowerLossDetector()
    assert pld.ac_ok is True
    fake_gpiozero[0].is_pressed = True
    assert pld.ac_ok is False
    pld.close()
    assert fake_gpiozero[0].closed


def test_charge_control_switches_and_closes_previous(fake_gpiozero):
    ctl = ChargeControl()
    assert ctl.enabled is None
    ctl.set_enabled(True)
    assert fake_gpiozero[0].pull_up is False       # pull-down = charging
    ctl.set_enabled(True)                          # tidak berubah -> tidak buat device baru
    assert len(fake_gpiozero) == 1
    ctl.set_enabled(False)
    assert fake_gpiozero[0].closed and fake_gpiozero[1].pull_up is True
    ctl.close()
    assert fake_gpiozero[1].closed and ctl.enabled is None


def test_charge_control_failure_resets_state(fake_gpiozero):
    ctl = ChargeControl()
    ctl.set_enabled(True)
    fake_gpiozero.fake_input.fail = True
    with pytest.raises(RuntimeError):
        ctl.set_enabled(False)
    assert ctl.enabled is None                     # status tidak diketahui -> dicoba lagi
    fake_gpiozero.fake_input.fail = False
    ctl.set_enabled(False)
    assert ctl.enabled is False
