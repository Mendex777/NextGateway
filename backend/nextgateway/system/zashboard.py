import hashlib
import json
import os
import platform
import secrets
import shutil
import urllib.request
import zipfile
from pathlib import Path

GITHUB_API = "https://api.github.com/repos/Zephyruso/zashboard/releases/tags/v{version}"
USER_AGENT = "NextGateway/0.1"
ASSET_NAME = "dist-no-fonts.zip"


def _release(version: str) -> tuple[str, str]:
    if not version or any(character not in "0123456789." for character in version):
        raise ValueError("Invalid Zashboard version")
    request = urllib.request.Request(
        GITHUB_API.format(version=version),
        headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        metadata = json.load(response)
    if metadata.get("tag_name") != f"v{version}" or metadata.get("draft") or metadata.get(
        "prerelease"
    ):
        raise ValueError("Zashboard release metadata is invalid")
    assets = [item for item in metadata.get("assets", []) if item.get("name") == ASSET_NAME]
    if len(assets) != 1:
        raise ValueError(f"Expected one {ASSET_NAME} release asset")
    digest = assets[0].get("digest", "")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Zashboard release asset has no SHA-256 digest")
    return assets[0]["browser_download_url"], digest.removeprefix("sha256:")


def _download(url: str, digest: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    calculated = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            calculated.update(chunk)
            output.write(chunk)
    if not secrets.compare_digest(calculated.hexdigest(), digest):
        target.unlink(missing_ok=True)
        raise ValueError("Zashboard archive checksum does not match release metadata")


def install_zashboard(version: str) -> dict[str, str]:
    if os.geteuid() != 0 or platform.system() != "Linux":
        raise PermissionError("Zashboard installation requires root on Linux")
    url, digest = _release(version)
    state_root = Path("/var/lib/nextgateway-system/zashboard")
    state_root.mkdir(parents=True, exist_ok=True)
    archive = state_root / f"zashboard-{version}.zip"
    _download(url, digest, archive)
    candidate = state_root / f"candidate-{version}"
    shutil.rmtree(candidate, ignore_errors=True)
    candidate.mkdir(mode=0o755)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            destination = (candidate / member.filename).resolve()
            outside_candidate = candidate.resolve() not in destination.parents
            if outside_candidate and destination != candidate.resolve():
                raise ValueError("Zashboard archive contains an unsafe path")
        bundle.extractall(candidate)
    source = candidate / "dist" if (candidate / "dist/index.html").is_file() else candidate
    if not (source / "index.html").is_file():
        raise ValueError("Zashboard archive does not contain dist/index.html")
    target = Path("/opt/nextgateway/zashboard")
    previous = target.with_name("zashboard.previous")
    shutil.rmtree(previous, ignore_errors=True)
    if target.exists():
        os.replace(target, previous)
    os.replace(source, target)
    for path in target.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return {"version": version, "asset": ASSET_NAME, "sha256": digest}
