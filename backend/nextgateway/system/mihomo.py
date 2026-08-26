import gzip
import hashlib
import json
import os
import platform
import secrets
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

GITHUB_API = "https://api.github.com/repos/MetaCubeX/mihomo/releases/tags/v{version}"
USER_AGENT = "NextGateway/0.1"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    url: str
    sha256: str


def select_release_asset(metadata: dict, version: str, machine: str) -> ReleaseAsset:
    if metadata.get("prerelease") or metadata.get("draft"):
        raise ValueError("Refusing to install a draft or prerelease")
    if metadata.get("tag_name") != f"v{version}":
        raise ValueError("Release tag does not match requested version")
    architecture = {"x86_64": "amd64-v1", "aarch64": "arm64"}.get(machine)
    if architecture is None:
        raise ValueError(f"Unsupported architecture: {machine}")
    expected_name = f"mihomo-linux-{architecture}-v{version}.gz"
    matches = [asset for asset in metadata.get("assets", []) if asset.get("name") == expected_name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one release asset named {expected_name}")
    asset = matches[0]
    digest = asset.get("digest", "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Release asset has no valid SHA-256 digest")
    return ReleaseAsset(
        name=expected_name,
        url=asset["browser_download_url"],
        sha256=digest.removeprefix("sha256:"),
    )


def fetch_release_asset(version: str) -> ReleaseAsset:
    request = urllib.request.Request(
        GITHUB_API.format(version=version),
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        metadata = json.load(response)
    return select_release_asset(metadata, version, platform.machine())


def download_verified(asset: ReleaseAsset, target: Path) -> None:
    request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    temporary = target.with_suffix(target.suffix + ".download")
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if not secrets.compare_digest(digest.hexdigest(), asset.sha256):
        temporary.unlink(missing_ok=True)
        raise ValueError("Downloaded Mihomo archive checksum does not match release metadata")
    os.replace(temporary, target)


def bootstrap_config(api_secret: str) -> str:
    config = {
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "allow-lan": False,
        "external-controller": "127.0.0.1:9090",
        "secret": api_secret,
        "tun": {"enable": False},
        "proxies": [],
        "proxy-groups": [],
        "rules": ["MATCH,DIRECT"],
    }
    return yaml.safe_dump(config, sort_keys=False)


def systemd_unit() -> str:
    return """[Unit]
Description=Mihomo proxy core
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=mihomo
Group=mihomo
WorkingDirectory=/var/lib/mihomo
ExecStart=/usr/local/bin/mihomo -d /var/lib/mihomo -f /etc/mihomo/config.yaml
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ReadWritePaths=/var/lib/mihomo /run
DevicePolicy=closed
DeviceAllow=/dev/net/tun rw
UMask=0077

[Install]
WantedBy=multi-user.target
"""


def _run(arguments: list[str], timeout: int = 60) -> None:
    subprocess.run(arguments, check=True, timeout=timeout)


def install_mihomo(version: str) -> dict[str, str]:
    if os.geteuid() != 0:
        raise PermissionError("Mihomo installation requires root")
    if not version or any(character not in "0123456789." for character in version):
        raise ValueError("Invalid Mihomo version")
    asset = fetch_release_asset(version)
    state_root = Path("/var/lib/nextgateway-system/mihomo")
    archive = state_root / asset.name
    download_verified(asset, archive)
    compressed_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not secrets.compare_digest(compressed_digest, asset.sha256):
        raise ValueError("Mihomo archive changed after verification")

    candidate = state_root / f"mihomo-{version}.candidate"
    with gzip.open(archive, "rb") as source, candidate.open("wb") as output:
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
    os.chmod(candidate, 0o755)
    _run([str(candidate), "-v"])

    if subprocess.run(["/usr/bin/getent", "passwd", "mihomo"], check=False).returncode != 0:
        _run(
            [
                "/usr/sbin/useradd", "--system", "--home", "/var/lib/mihomo",
                "--shell", "/usr/sbin/nologin", "mihomo",
            ]
        )
    Path("/etc/mihomo").mkdir(mode=0o750, exist_ok=True)
    Path("/var/lib/mihomo").mkdir(mode=0o750, exist_ok=True)
    _run(["/usr/bin/chown", "root:mihomo", "/etc/mihomo"])
    _run(["/usr/bin/chown", "mihomo:mihomo", "/var/lib/mihomo"])

    secret_path = Path("/etc/nextgateway/secrets/mihomo-api")
    secret_root = secret_path.parent.parent
    secret_root.mkdir(parents=True, mode=0o750, exist_ok=True)
    os.chmod(secret_root, 0o750)
    _run(["/usr/bin/chown", "root:nextgateway", str(secret_root)])
    secret_path.parent.mkdir(parents=True, mode=0o750, exist_ok=True)
    os.chmod(secret_path.parent, 0o750)
    _run(["/usr/bin/chown", "root:nextgateway", str(secret_path.parent)])
    api_secret = (
        secret_path.read_text().strip() if secret_path.exists() else secrets.token_urlsafe(32)
    )
    if not secret_path.exists():
        secret_path.write_text(api_secret)
    os.chmod(secret_path, 0o640)
    _run(["/usr/bin/chown", "root:nextgateway", str(secret_path)])

    config_path = Path("/etc/mihomo/config.yaml")
    if not config_path.exists():
        config_path.write_text(bootstrap_config(api_secret))
        os.chmod(config_path, 0o600)
        _run(["/usr/bin/chown", "mihomo:mihomo", str(config_path)])
    _run([str(candidate), "-t", "-d", "/var/lib/mihomo", "-f", str(config_path)])

    os.replace(candidate, "/usr/local/bin/mihomo")
    unit_path = Path("/etc/systemd/system/mihomo.service")
    unit_path.write_text(systemd_unit())
    os.chmod(unit_path, 0o644)
    _run(["/usr/bin/systemctl", "daemon-reload"])
    _run(["/usr/bin/systemctl", "enable", "--now", "mihomo.service"])
    return {"version": version, "asset": asset.name, "sha256": asset.sha256}
