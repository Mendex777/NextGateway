import json
import secrets
import signal
import subprocess

from ..settings import settings
from .gateway import GatewayConfig
from .network import NetworkConfig, validate_operation_id


class HelperError(RuntimeError):
    pass


SYSTEM_UPDATE_UNITS = ("apt-daily-upgrade.service", "apt-daily.service")


def _ensure_system_updates_idle() -> None:
    for unit in SYSTEM_UPDATE_UNITS:
        result = subprocess.run(
            ["/usr/bin/systemctl", "show", "--property=ActiveState", "--value", unit],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() in {"active", "activating", "reloading"}:
            raise HelperError(
                "Ubuntu is installing system updates. Wait for the update to finish "
                "and repeat this action. No changes were applied."
            )


def _call(arguments: list[str], input_text: str | None = None, timeout: int = 45) -> str:
    if arguments[0] in {
        "prepare-network",
        "prepare-gateway",
        "prepare-mihomo-config",
        "install-mihomo",
        "install-zashboard",
    }:
        _ensure_system_updates_idle()
    command = [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/systemd-run",
        "--pipe",
        "--wait",
        "--collect",
        "--quiet",
        str(settings.helper_path),
        *arguments,
    ]
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=True,
            timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        if isinstance(exc, subprocess.CalledProcessError) and exc.returncode == -signal.SIGTERM:
            raise HelperError(
                "The NextGateway service was restarted while the operation was starting. "
                "Repeat this action; no network changes were applied."
            ) from None
        message = getattr(exc, "stderr", None) or str(exc)
        raise HelperError(f"Privileged helper failed: {message.strip()}") from None
    return result.stdout


def begin_network_apply(config: NetworkConfig) -> str:
    operation_id = secrets.token_hex(16)
    _call(["prepare-network", "--operation-id", operation_id], config.model_dump_json())
    _call(["apply-network", operation_id])
    return operation_id


def confirm_network_apply(operation_id: str) -> None:
    _call(["confirm-network", validate_operation_id(operation_id)])


def network_apply_status(operation_id: str) -> dict:
    output = _call(["status", validate_operation_id(operation_id)])
    return json.loads(output)


def install_mihomo(version: str) -> dict:
    _call(["install-mihomo", version], timeout=180)
    return {"version": version}


def install_zashboard(version: str) -> dict:
    _call(["install-zashboard", version], timeout=180)
    return {"version": version}


def begin_gateway_apply(config: GatewayConfig) -> str:
    operation_id = secrets.token_hex(16)
    _call(["prepare-gateway", "--operation-id", operation_id], config.model_dump_json())
    _call(["apply-gateway", operation_id])
    return operation_id


def confirm_gateway_apply(operation_id: str) -> None:
    _call(["confirm-gateway", validate_operation_id(operation_id)])


def gateway_apply_status(operation_id: str) -> dict:
    output = _call(["gateway-status", validate_operation_id(operation_id)])
    return json.loads(output)


def begin_mihomo_apply(config_yaml: str, timeout: int) -> str:
    operation_id = secrets.token_hex(16)
    _call(["prepare-mihomo-config", "--operation-id", operation_id], config_yaml)
    _call(["apply-mihomo-config", operation_id, "--timeout", str(timeout)])
    return operation_id


def confirm_mihomo_apply(operation_id: str) -> None:
    _call(["confirm-mihomo-config", validate_operation_id(operation_id)])


def mihomo_apply_status(operation_id: str) -> dict:
    output = _call(["mihomo-config-status", validate_operation_id(operation_id)])
    return json.loads(output)


def current_mihomo_config_digest() -> str:
    output = _call(["mihomo-current-config-digest"])
    return json.loads(output)["digest"]
