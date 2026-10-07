import x120x.shutdown as sd


def _capture(monkeypatch, euid):
    calls = []
    monkeypatch.setattr(sd.os, "geteuid", lambda: euid, raising=False)
    monkeypatch.setattr(sd.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw)))
    return calls


def test_schedule_as_root(monkeypatch):
    calls = _capture(monkeypatch, 0)
    sd.SystemShutdown().schedule(5)
    cmd, kw = calls[0]
    assert cmd[:3] == ["shutdown", "-P", "+5"]
    assert kw["check"] is True and kw["timeout"] == sd.CMD_TIMEOUT_S


def test_schedule_non_root_uses_sudo_without_password(monkeypatch):
    calls = _capture(monkeypatch, 1000)
    sd.SystemShutdown().schedule(2)
    assert calls[0][0][:4] == ["sudo", "-n", "shutdown", "-P"]


def test_cancel_does_not_raise_on_failure_exit(monkeypatch):
    calls = _capture(monkeypatch, 0)
    sd.SystemShutdown().cancel()
    cmd, kw = calls[0]
    assert cmd[:2] == ["shutdown", "-c"] and kw["check"] is False


def test_log_only_never_runs_commands(monkeypatch):
    calls = _capture(monkeypatch, 0)
    action = sd.LogOnlyShutdown()
    action.schedule(5)
    action.cancel()
    assert calls == []
