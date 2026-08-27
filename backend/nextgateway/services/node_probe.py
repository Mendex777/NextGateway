import json
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from ..settings import settings


class NodeProbeError(RuntimeError):
    pass


def _controller_delay(name: str, api_url: str, secret: str, timeout_ms: int) -> int:
    encoded = urllib.parse.quote(name, safe="")
    query = urllib.parse.urlencode(
        {"url": "https://www.gstatic.com/generate_204", "timeout": timeout_ms}
    )
    request = urllib.request.Request(
        f"{api_url}/proxies/{encoded}/delay?{query}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_ms / 1000 + 2) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = payload.get("message") or str(exc)
        except (ValueError, OSError):
            message = str(exc)
        raise NodeProbeError(message) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise NodeProbeError(str(exc)) from exc
    delay = payload.get("delay")
    if not isinstance(delay, int) or delay <= 0:
        raise NodeProbeError("Mihomo did not return a valid delay")
    return delay


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _probe_isolated(proxy: dict[str, Any], timeout_ms: int) -> int:
    if not settings.mihomo_binary_path.exists():
        raise NodeProbeError("Mihomo is not installed")

    port = _free_local_port()
    secret = secrets.token_urlsafe(24)
    name = str(proxy["name"])
    config = {
        "external-controller": f"127.0.0.1:{port}",
        "secret": secret,
        "log-level": "silent",
        "ipv6": False,
        "proxies": [proxy],
        "proxy-groups": [{"name": "NextGateway Probe", "type": "select", "proxies": [name]}],
        "rules": ["MATCH,NextGateway Probe"],
    }
    with tempfile.TemporaryDirectory(prefix="nextgateway-probe-") as directory:
        config_path = Path(directory) / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        process = subprocess.Popen(
            [
                str(settings.mihomo_binary_path),
                "-d",
                directory,
                "-f",
                str(config_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        api_url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    error = (process.stderr.read() if process.stderr else "").strip()
                    raise NodeProbeError(error or "Temporary Mihomo process stopped")
                try:
                    return _controller_delay(name, api_url, secret, timeout_ms)
                except NodeProbeError as exc:
                    if not any(
                        marker in str(exc)
                        for marker in ("Connection refused", "Resource not found")
                    ):
                        raise
                    time.sleep(0.05)
            raise NodeProbeError("Temporary Mihomo API did not become ready")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


def probe_node(
    name: str,
    timeout_ms: int = 5000,
    api_url: str | None = None,
    proxy: dict[str, Any] | None = None,
) -> int:
    secret = settings.mihomo_secret_path.read_text().strip()
    try:
        return _controller_delay(name, api_url or settings.mihomo_api_url, secret, timeout_ms)
    except NodeProbeError as exc:
        if proxy is None or "Resource not found" not in str(exc):
            raise
    return _probe_isolated(proxy, timeout_ms)
