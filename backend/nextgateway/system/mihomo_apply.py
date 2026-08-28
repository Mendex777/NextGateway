import hashlib
import ipaddress
import json
import os
import subprocess
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..services.yaml_output import dump_mihomo_document
from .network import validate_operation_id

MIHOMO = "/usr/local/bin/mihomo"
SYSTEMCTL = "/usr/bin/systemctl"
SYSTEMD_RUN = "/usr/bin/systemd-run"
HELPER = "/opt/nextgateway/venv/bin/nextgateway-helper"
CONFIG = Path("/etc/mihomo/config.yaml")
SECRET = Path("/etc/nextgateway/secrets/mihomo-api")
STATE_ROOT = Path("/var/lib/nextgateway-system/mihomo-operations")


def normalized_config_digest(document: dict) -> str:
    safe = dict(document)
    safe.pop("secret", None)
    canonical = json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def current_config_digest() -> str:
    document = yaml.safe_load(CONFIG.read_text())
    if not isinstance(document, dict):
        raise ValueError("Applied Mihomo configuration must be a mapping")
    return normalized_config_digest(document)


def _run(arguments: list[str], timeout: int = 45, check: bool = True) -> None:
    subprocess.run(arguments, check=check, timeout=timeout)


def _validate_config(path: Path) -> None:
    result = subprocess.run(
        [MIHOMO, "-t", "-d", "/var/lib/mihomo", "-f", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode:
        details = (result.stderr or result.stdout).strip().splitlines()
        message = details[-1] if details else f"Mihomo exited with status {result.returncode}"
        raise RuntimeError(f"Mihomo configuration validation failed: {message}")


def _write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _directory(operation_id: str) -> Path:
    return STATE_ROOT / validate_operation_id(operation_id)


def _state(directory: Path, state: str, **extra: object) -> None:
    payload = {"state": state, "updated_at": datetime.now(UTC).isoformat(), **extra}
    _write(directory / "state.json", json.dumps(payload, indent=2).encode())


def _cancel_timer(operation_id: str) -> None:
    unit = f"nextgateway-mihomo-rollback-{operation_id}.timer"
    _run([SYSTEMCTL, "stop", unit], check=False)


def _wait_for_api(timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    document = yaml.safe_load(CONFIG.read_text())
    controller = document.get("external-controller", "127.0.0.1:9090")
    while time.monotonic() < deadline:
        request = urllib.request.Request(
            f"http://{controller}/version",
            headers={"Authorization": f"Bearer {SECRET.read_text().strip()}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Mihomo API did not become ready: {last_error}")


def prepare_config(candidate_yaml: str, operation_id: str | None = None) -> str:
    document = yaml.safe_load(candidate_yaml)
    if not isinstance(document, dict):
        raise ValueError("Mihomo configuration must be a YAML mapping")
    controller = document.get("external-controller", "127.0.0.1:9090")
    try:
        controller_host, controller_port = controller.rsplit(":", maxsplit=1)
        controller_ip = ipaddress.ip_address(controller_host)
    except (AttributeError, ValueError):
        controller_ip = ipaddress.ip_address("127.0.0.1")
        controller_port = "9090"
    safe_address = (controller_ip.is_private or controller_ip.is_loopback) and not (
        controller_ip.is_unspecified or controller_ip.is_multicast
    )
    if controller_port != "9090" or not safe_address:
        controller_ip = ipaddress.ip_address("127.0.0.1")
    document["external-controller"] = f"{controller_ip}:9090"
    document["secret"] = SECRET.read_text().strip()
    operation_id = validate_operation_id(operation_id or uuid.uuid4().hex)
    directory = _directory(operation_id)
    directory.mkdir(parents=True, mode=0o700)
    _write(directory / "config.backup", CONFIG.read_bytes())
    rendered = dump_mihomo_document(document).encode()
    _write(directory / "config.candidate", rendered)
    _validate_config(directory / "config.candidate")
    _state(directory, "prepared")
    return operation_id


def apply_config(operation_id: str, timeout: int = 120) -> None:
    if not 30 <= timeout <= 300:
        raise ValueError("Rollback timeout must be between 30 and 300 seconds")
    directory = _directory(operation_id)
    _write(CONFIG, (directory / "config.candidate").read_bytes())
    _run(["/usr/bin/chown", "mihomo:mihomo", str(CONFIG)])
    unit = f"nextgateway-mihomo-rollback-{operation_id}"
    try:
        _run(
            [
                SYSTEMD_RUN,
                "--unit",
                unit,
                "--on-active",
                f"{timeout}s",
                HELPER,
                "rollback-mihomo",
                operation_id,
            ]
        )
        _state(directory, "pending_confirmation", rollback_unit=unit)
        _run([SYSTEMCTL, "restart", "mihomo.service"])
        _run([SYSTEMCTL, "is-active", "--quiet", "mihomo.service"])
        _wait_for_api()
    except Exception as exc:
        _cancel_timer(operation_id)
        rollback_config(operation_id)
        raise RuntimeError(f"Mihomo apply failed and was rolled back: {exc}") from exc


def confirm_config(operation_id: str) -> None:
    directory = _directory(operation_id)
    current = json.loads((directory / "state.json").read_text())
    if current["state"] != "pending_confirmation":
        raise RuntimeError("Mihomo operation is not waiting for confirmation")
    _cancel_timer(operation_id)
    _state(directory, "confirmed")


def rollback_config(operation_id: str) -> None:
    directory = _directory(operation_id)
    _write(CONFIG, (directory / "config.backup").read_bytes())
    _run(["/usr/bin/chown", "mihomo:mihomo", str(CONFIG)])
    _run([SYSTEMCTL, "restart", "mihomo.service"])
    _state(directory, "rolled_back")


def config_status(operation_id: str) -> dict:
    return json.loads((_directory(operation_id) / "state.json").read_text())
