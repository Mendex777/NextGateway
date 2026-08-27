import signal
import subprocess

import pytest
from nextgateway.system import client


def test_mutating_helper_is_blocked_during_system_update(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:3] == ["/usr/bin/systemctl", "show", "--property=ActiveState"]:
            return subprocess.CompletedProcess(command, 0, stdout="activating\n", stderr="")
        raise AssertionError("The privileged helper must not start during an OS update")

    monkeypatch.setattr(client.subprocess, "run", fake_run)

    with pytest.raises(client.HelperError, match="Ubuntu is installing system updates"):
        client._call(["prepare-network", "--operation-id", "a" * 32], "{}")

    assert calls == [
        [
            "/usr/bin/systemctl",
            "show",
            "--property=ActiveState",
            "--value",
            "apt-daily-upgrade.service",
        ]
    ]


def test_status_helper_remains_available_during_system_update(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        assert any(part.endswith("nextgateway-helper") for part in command)
        return subprocess.CompletedProcess(command, 0, stdout='{"state": "prepared"}', stderr="")

    monkeypatch.setattr(client.subprocess, "run", fake_run)

    assert client._call(["status", "a" * 32]) == '{"state": "prepared"}'


def test_sigterm_has_retryable_message(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        if command[:3] == ["/usr/bin/systemctl", "show", "--property=ActiveState"]:
            return subprocess.CompletedProcess(command, 0, stdout="inactive\n", stderr="")
        raise subprocess.CalledProcessError(-signal.SIGTERM, command)

    monkeypatch.setattr(client.subprocess, "run", fake_run)

    with pytest.raises(client.HelperError, match="service was restarted"):
        client._call(["prepare-network", "--operation-id", "a" * 32], "{}")
