import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .gateway import (
    GatewayConfig,
    apply_gateway,
    confirm_gateway,
    gateway_status,
    prepare_gateway,
    rollback_gateway,
)
from .mihomo import install_mihomo
from .mihomo_apply import (
    apply_config,
    config_status,
    confirm_config,
    current_config_digest,
    prepare_config,
    rollback_config,
)
from .network import NetworkConfig, NetworkPaths, render_netplan, validate_operation_id
from .zashboard import install_zashboard

NETPLAN = "/usr/sbin/netplan"
SYSTEMCTL = "/usr/bin/systemctl"
SYSTEMD_RUN = "/usr/bin/systemd-run"
HELPER = "/opt/nextgateway/venv/bin/nextgateway-helper"
DEFAULT_PATHS = NetworkPaths()


def _require_root() -> None:
    if os.geteuid() != 0:
        raise PermissionError("nextgateway-helper must run as root")


def _run(arguments: list[str]) -> None:
    subprocess.run(arguments, check=True, timeout=30)


def _stop_unit(unit: str) -> None:
    subprocess.run(
        [SYSTEMCTL, "stop", unit],
        check=False,
        timeout=30,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _operation_dir(paths: NetworkPaths, operation_id: str) -> Path:
    return paths.state_root / validate_operation_id(operation_id)


def _write_state(directory: Path, state: str, **extra: object) -> None:
    payload = {"state": state, "updated_at": datetime.now(UTC).isoformat(), **extra}
    _atomic_write(directory / "state.json", json.dumps(payload, indent=2).encode())


def prepare(
    config: NetworkConfig,
    paths: NetworkPaths = DEFAULT_PATHS,
    operation_id: str | None = None,
) -> str:
    _require_root()
    operation_id = validate_operation_id(operation_id or uuid.uuid4().hex)
    directory = _operation_dir(paths, operation_id)
    directory.mkdir(parents=True, mode=0o700)
    previous = paths.managed_config.read_bytes() if paths.managed_config.exists() else None
    if previous is None:
        _atomic_write(directory / "managed-config.absent", b"")
    else:
        _atomic_write(directory / "managed-config.backup", previous)
    _atomic_write(directory / "request.json", config.model_dump_json(indent=2).encode())
    _atomic_write(directory / "candidate.yaml", render_netplan(config).encode())
    _write_state(directory, "prepared")
    return operation_id


def apply(operation_id: str, paths: NetworkPaths = DEFAULT_PATHS) -> None:
    _require_root()
    directory = _operation_dir(paths, operation_id)
    config = NetworkConfig.model_validate_json((directory / "request.json").read_text())
    _atomic_write(paths.managed_config, (directory / "candidate.yaml").read_bytes())
    try:
        _run([NETPLAN, "generate"])
        unit = f"nextgateway-network-rollback-{operation_id}"
        _run(
            [
                SYSTEMD_RUN,
                "--unit",
                unit,
                "--on-active",
                f"{config.rollback_timeout}s",
                HELPER,
                "rollback",
                operation_id,
            ]
        )
        _write_state(directory, "pending_confirmation", rollback_unit=unit)
        _run([NETPLAN, "apply"])
        _run(["/usr/bin/ping", "-c", "1", "-W", "3", config.gateway])
    except Exception as exc:
        _stop_unit(f"nextgateway-network-rollback-{operation_id}.timer")
        rollback(operation_id, paths)
        raise RuntimeError(f"Network apply failed and was rolled back: {exc}") from exc


def confirm(operation_id: str, paths: NetworkPaths = DEFAULT_PATHS) -> None:
    _require_root()
    directory = _operation_dir(paths, operation_id)
    state = json.loads((directory / "state.json").read_text())
    if state["state"] != "pending_confirmation":
        raise RuntimeError("Network operation is not waiting for confirmation")
    unit = state["rollback_unit"]
    _stop_unit(f"{unit}.timer")
    _stop_unit(f"{unit}.service")
    _write_state(directory, "confirmed")


def rollback(operation_id: str, paths: NetworkPaths = DEFAULT_PATHS) -> None:
    _require_root()
    directory = _operation_dir(paths, operation_id)
    backup = directory / "managed-config.backup"
    absent = directory / "managed-config.absent"
    if backup.exists():
        _atomic_write(paths.managed_config, backup.read_bytes())
    elif absent.exists() and paths.managed_config.exists():
        paths.managed_config.unlink()
    else:
        raise RuntimeError("Network backup marker is missing")
    _run([NETPLAN, "generate"])
    _run([NETPLAN, "apply"])
    _write_state(directory, "rolled_back")


def status(operation_id: str, paths: NetworkPaths = DEFAULT_PATHS) -> dict:
    directory = _operation_dir(paths, operation_id)
    return json.loads((directory / "state.json").read_text())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nextgateway-helper")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_network_parser = commands.add_parser("prepare-network")
    prepare_network_parser.add_argument("--operation-id")
    prepare_gateway_parser = commands.add_parser("prepare-gateway")
    prepare_gateway_parser.add_argument("--operation-id")
    install_parser = commands.add_parser("install-mihomo")
    install_parser.add_argument("version")
    zashboard_parser = commands.add_parser("install-zashboard")
    zashboard_parser.add_argument("version")
    prepare_mihomo_parser = commands.add_parser("prepare-mihomo-config")
    prepare_mihomo_parser.add_argument("--operation-id")
    apply_mihomo_parser = commands.add_parser("apply-mihomo-config")
    apply_mihomo_parser.add_argument("operation_id")
    apply_mihomo_parser.add_argument("--timeout", type=int, default=120)
    for command in ("confirm-mihomo-config", "rollback-mihomo", "mihomo-config-status"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("operation_id")
    commands.add_parser("mihomo-current-config-digest")
    apply_gateway_parser = commands.add_parser("apply-gateway")
    apply_gateway_parser.add_argument("operation_id")
    apply_gateway_parser.add_argument("--timeout", type=int, default=120)
    for command in ("confirm-gateway", "rollback-gateway", "gateway-status"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("operation_id")
    for command in ("apply-network", "confirm-network", "rollback", "status"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("operation_id")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    try:
        if arguments.command == "prepare-network":
            request_text = sys.stdin.read(16385)
            if len(request_text) > 16384:
                raise ValueError("Network request is too large")
            request = NetworkConfig.model_validate_json(request_text)
            print(
                json.dumps(
                    {
                        "operation_id": prepare(
                            request, operation_id=arguments.operation_id
                        )
                    }
                )
            )
        elif arguments.command == "prepare-gateway":
            request_text = sys.stdin.read(16385)
            if len(request_text) > 16384:
                raise ValueError("Gateway request is too large")
            request = GatewayConfig.model_validate_json(request_text)
            print(
                json.dumps(
                    {"operation_id": prepare_gateway(request, arguments.operation_id)}
                )
            )
        elif arguments.command == "install-mihomo":
            print(json.dumps(install_mihomo(arguments.version)))
        elif arguments.command == "install-zashboard":
            print(json.dumps(install_zashboard(arguments.version)))
        elif arguments.command == "prepare-mihomo-config":
            config_text = sys.stdin.read(2 * 1024 * 1024 + 1)
            if len(config_text) > 2 * 1024 * 1024:
                raise ValueError("Mihomo configuration is too large")
            print(
                json.dumps(
                    {"operation_id": prepare_config(config_text, arguments.operation_id)}
                )
            )
        elif arguments.command == "apply-mihomo-config":
            apply_config(arguments.operation_id, arguments.timeout)
        elif arguments.command == "confirm-mihomo-config":
            confirm_config(arguments.operation_id)
        elif arguments.command == "rollback-mihomo":
            rollback_config(arguments.operation_id)
        elif arguments.command == "mihomo-config-status":
            print(json.dumps(config_status(arguments.operation_id)))
        elif arguments.command == "mihomo-current-config-digest":
            print(json.dumps({"digest": current_config_digest()}))
        elif arguments.command == "apply-gateway":
            apply_gateway(arguments.operation_id, arguments.timeout)
        elif arguments.command == "confirm-gateway":
            confirm_gateway(arguments.operation_id)
        elif arguments.command == "rollback-gateway":
            rollback_gateway(arguments.operation_id)
        elif arguments.command == "gateway-status":
            print(json.dumps(gateway_status(arguments.operation_id)))
        elif arguments.command == "apply-network":
            apply(arguments.operation_id)
        elif arguments.command == "confirm-network":
            confirm(arguments.operation_id)
        elif arguments.command == "rollback":
            rollback(arguments.operation_id)
        elif arguments.command == "status":
            print(json.dumps(status(arguments.operation_id)))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
