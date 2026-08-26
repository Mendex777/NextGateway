import ipaddress
import json
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from .network import INTERFACE_PATTERN, validate_operation_id

SYSCTL_FILE = Path("/etc/sysctl.d/90-nextgateway.conf")
NFT_FILE = Path("/etc/nextgateway/nftables-gateway.nft")
UNIT_FILE = Path("/etc/systemd/system/nextgateway-firewall.service")
STATE_ROOT = Path("/var/lib/nextgateway-system/gateway-operations")
SYSTEMCTL = "/usr/bin/systemctl"
SYSTEMD_RUN = "/usr/bin/systemd-run"
HELPER = "/opt/nextgateway/venv/bin/nextgateway-helper"


class GatewayConfig(BaseModel):
    interface: str
    lan_subnet: str
    rollback_timeout: int = Field(default=120, ge=30, le=300)

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        if not INTERFACE_PATTERN.fullmatch(value):
            raise ValueError("Invalid interface name")
        return value

    @field_validator("lan_subnet")
    @classmethod
    def validate_subnet(cls, value: str) -> str:
        network = ipaddress.IPv4Network(value, strict=True)
        if not network.is_private:
            raise ValueError("LAN subnet must be private")
        return str(network)


def render_sysctl() -> str:
    return """# Managed by NextGateway
net.ipv4.ip_forward = 1
net.ipv4.conf.all.rp_filter = 2
net.ipv4.conf.default.rp_filter = 2
"""


def render_nftables(config: GatewayConfig) -> str:
    return f"""table inet nextgateway {{
    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        ip saddr {config.lan_subnet} oifname \"{config.interface}\" masquerade
    }}
}}
"""


def render_unit() -> str:
    return """[Unit]
Description=NextGateway managed nftables rules
After=network-online.target
Before=mihomo.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/nextgateway/nftables-gateway.nft
ExecStop=-/usr/sbin/nft delete table inet nextgateway

[Install]
WantedBy=multi-user.target
"""


def _run(arguments: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, check=check, timeout=30, capture_output=True, text=True)


def _write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _directory(operation_id: str) -> Path:
    return STATE_ROOT / validate_operation_id(operation_id)


def _state(directory: Path, state: str, **extra: object) -> None:
    data = {"state": state, "updated_at": datetime.now(UTC).isoformat(), **extra}
    _write(directory / "state.json", json.dumps(data, indent=2).encode())


def _backup(directory: Path, name: str, path: Path) -> None:
    if path.exists():
        _write(directory / f"{name}.backup", path.read_bytes())
    else:
        _write(directory / f"{name}.absent", b"")


def _restore(directory: Path, name: str, path: Path, mode: int) -> None:
    backup = directory / f"{name}.backup"
    if backup.exists():
        _write(path, backup.read_bytes(), mode)
    elif (directory / f"{name}.absent").exists():
        path.unlink(missing_ok=True)
    else:
        raise RuntimeError(f"Missing backup marker for {name}")


def prepare_gateway(config: GatewayConfig, operation_id: str | None = None) -> str:
    operation_id = validate_operation_id(operation_id or uuid.uuid4().hex)
    directory = _directory(operation_id)
    directory.mkdir(parents=True, mode=0o700)
    for name, path in (("sysctl", SYSCTL_FILE), ("nft", NFT_FILE), ("unit", UNIT_FILE)):
        _backup(directory, name, path)
    runtime = {
        "ip_forward": Path("/proc/sys/net/ipv4/ip_forward").read_text().strip(),
        "rp_filter_all": Path("/proc/sys/net/ipv4/conf/all/rp_filter").read_text().strip(),
        "rp_filter_default": Path("/proc/sys/net/ipv4/conf/default/rp_filter").read_text().strip(),
    }
    _write(directory / "runtime.json", json.dumps(runtime).encode())
    _write(directory / "sysctl.candidate", render_sysctl().encode())
    _write(directory / "nft.candidate", render_nftables(config).encode())
    _write(directory / "unit.candidate", render_unit().encode())
    _run(["/usr/sbin/nft", "-c", "-f", str(directory / "nft.candidate")])
    _state(directory, "prepared")
    return operation_id


def apply_gateway(operation_id: str, timeout: int = 120) -> None:
    directory = _directory(operation_id)
    _write(SYSCTL_FILE, (directory / "sysctl.candidate").read_bytes())
    _write(NFT_FILE, (directory / "nft.candidate").read_bytes())
    _write(UNIT_FILE, (directory / "unit.candidate").read_bytes(), 0o644)
    unit = f"nextgateway-gateway-rollback-{operation_id}"
    try:
        _run([SYSTEMCTL, "daemon-reload"])
        _run(
            [
                SYSTEMD_RUN, "--unit", unit, "--on-active", f"{timeout}s",
                HELPER, "rollback-gateway", operation_id,
            ]
        )
        _state(directory, "pending_confirmation", rollback_unit=unit)
        _run(["/usr/sbin/sysctl", "-p", str(SYSCTL_FILE)])
        _run([SYSTEMCTL, "enable", "--now", "nextgateway-firewall.service"])
        _run(["/usr/sbin/nft", "list", "table", "inet", "nextgateway"])
        if Path("/proc/sys/net/ipv4/ip_forward").read_text().strip() != "1":
            raise RuntimeError("IPv4 forwarding did not become active")
    except Exception as exc:
        _run([SYSTEMCTL, "stop", f"{unit}.timer"], check=False)
        rollback_gateway(operation_id)
        raise RuntimeError(f"Gateway apply failed and was rolled back: {exc}") from exc


def confirm_gateway(operation_id: str) -> None:
    directory = _directory(operation_id)
    current = json.loads((directory / "state.json").read_text())
    if current["state"] != "pending_confirmation":
        raise RuntimeError("Gateway operation is not waiting for confirmation")
    _run([SYSTEMCTL, "stop", f"nextgateway-gateway-rollback-{operation_id}.timer"], check=False)
    _state(directory, "confirmed")


def rollback_gateway(operation_id: str) -> None:
    directory = _directory(operation_id)
    _run([SYSTEMCTL, "disable", "--now", "nextgateway-firewall.service"], check=False)
    _restore(directory, "sysctl", SYSCTL_FILE, 0o600)
    _restore(directory, "nft", NFT_FILE, 0o600)
    _restore(directory, "unit", UNIT_FILE, 0o644)
    runtime = json.loads((directory / "runtime.json").read_text())
    for key, value in (
        ("net.ipv4.ip_forward", runtime["ip_forward"]),
        ("net.ipv4.conf.all.rp_filter", runtime["rp_filter_all"]),
        ("net.ipv4.conf.default.rp_filter", runtime["rp_filter_default"]),
    ):
        _run(["/usr/sbin/sysctl", "-w", f"{key}={value}"])
    _run([SYSTEMCTL, "daemon-reload"])
    _state(directory, "rolled_back")


def gateway_status(operation_id: str) -> dict:
    return json.loads((_directory(operation_id) / "state.json").read_text())
