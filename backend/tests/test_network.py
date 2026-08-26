import json
from pathlib import Path

import pytest
from nextgateway.system import helper
from nextgateway.system.network import NetworkConfig, NetworkPaths, render_netplan


def config() -> NetworkConfig:
    return NetworkConfig(
        interface="ens18",
        address="192.168.1.84/24",
        gateway="192.168.1.1",
        dns=["192.168.1.1"],
        rollback_timeout=30,
    )


def paths(tmp_path: Path) -> NetworkPaths:
    return NetworkPaths(
        managed_config=tmp_path / "etc/netplan/90-nextgateway.yaml",
        state_root=tmp_path / "var/lib/nextgateway/network-operations",
    )


def test_render_static_single_arm_netplan() -> None:
    output = render_netplan(config())
    assert "dhcp4: false" in output
    assert "192.168.1.84/24" in output
    assert "via: 192.168.1.1" in output


def test_reject_off_link_gateway() -> None:
    with pytest.raises(ValueError, match="configured IPv4 subnet"):
        NetworkConfig(
            interface="ens18",
            address="192.168.1.84/24",
            gateway="10.0.0.1",
            dns=["192.168.1.1"],
        )


def test_failed_apply_restores_previous_config(tmp_path: Path, monkeypatch) -> None:
    network_paths = paths(tmp_path)
    network_paths.managed_config.parent.mkdir(parents=True)
    network_paths.managed_config.write_text("previous")
    monkeypatch.setattr(helper, "_require_root", lambda: None)

    operation_id = helper.prepare(config(), network_paths)
    calls = 0

    def fail_first_apply(arguments: list[str]) -> None:
        nonlocal calls
        calls += 1
        if arguments == [helper.NETPLAN, "apply"] and calls < 5:
            raise RuntimeError("simulated lost network")

    monkeypatch.setattr(helper, "_run", fail_first_apply)
    stopped: list[str] = []
    monkeypatch.setattr(helper, "_stop_unit", stopped.append)
    with pytest.raises(RuntimeError, match="rolled back"):
        helper.apply(operation_id, network_paths)

    assert network_paths.managed_config.read_text() == "previous"
    state = json.loads((network_paths.state_root / operation_id / "state.json").read_text())
    assert state["state"] == "rolled_back"
    assert stopped == [f"nextgateway-network-rollback-{operation_id}.timer"]


def test_absent_managed_config_is_removed_on_rollback(tmp_path: Path, monkeypatch) -> None:
    network_paths = paths(tmp_path)
    monkeypatch.setattr(helper, "_require_root", lambda: None)
    monkeypatch.setattr(helper, "_run", lambda _arguments: None)
    operation_id = helper.prepare(config(), network_paths)
    helper.apply(operation_id, network_paths)
    assert network_paths.managed_config.exists()
    helper.rollback(operation_id, network_paths)
    assert not network_paths.managed_config.exists()


def test_confirm_is_idempotent_for_unloaded_transient_service(tmp_path: Path, monkeypatch) -> None:
    network_paths = paths(tmp_path)
    monkeypatch.setattr(helper, "_require_root", lambda: None)
    monkeypatch.setattr(helper, "_run", lambda _arguments: None)
    stopped: list[str] = []
    monkeypatch.setattr(helper, "_stop_unit", stopped.append)
    operation_id = helper.prepare(config(), network_paths)
    helper.apply(operation_id, network_paths)
    helper.confirm(operation_id, network_paths)
    state = json.loads((network_paths.state_root / operation_id / "state.json").read_text())
    assert state["state"] == "confirmed"
    assert stopped == [
        f"nextgateway-network-rollback-{operation_id}.timer",
        f"nextgateway-network-rollback-{operation_id}.service",
    ]
