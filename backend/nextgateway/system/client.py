import json
import secrets
import subprocess

from ..settings import settings
from .gateway import GatewayConfig
from .network import NetworkConfig, validate_operation_id


class HelperError(RuntimeError):
    pass


def _call(arguments: list[str], input_text: str | None = None, timeout: int = 45) -> str:
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
