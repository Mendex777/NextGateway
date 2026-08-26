import hashlib
from pathlib import Path

import pytest
from nextgateway.system.mihomo import (
    ReleaseAsset,
    bootstrap_config,
    download_verified,
    select_release_asset,
    systemd_unit,
)


def metadata(version: str = "1.19.30", digest: str = "a" * 64) -> dict:
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": f"mihomo-linux-amd64-v1-v{version}.gz",
                "digest": f"sha256:{digest}",
                "browser_download_url": "https://example.invalid/mihomo.gz",
            }
        ],
    }


def test_select_exact_stable_asset() -> None:
    asset = select_release_asset(metadata(), "1.19.30", "x86_64")
    assert asset.name == "mihomo-linux-amd64-v1-v1.19.30.gz"
    assert asset.sha256 == "a" * 64


def test_reject_prerelease() -> None:
    release = metadata()
    release["prerelease"] = True
    with pytest.raises(ValueError, match="prerelease"):
        select_release_asset(release, "1.19.30", "x86_64")


def test_download_rejects_bad_checksum(tmp_path: Path, monkeypatch) -> None:
    content = b"not-a-real-archive"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _size: int) -> bytes:
            result, self.content = getattr(self, "content", content), b""
            return result

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    asset = ReleaseAsset("mihomo.gz", "https://example.invalid", "0" * 64)
    with pytest.raises(ValueError, match="checksum"):
        download_verified(asset, tmp_path / "mihomo.gz")
    assert not (tmp_path / "mihomo.gz.download").exists()
    assert hashlib.sha256(content).hexdigest() != asset.sha256


def test_bootstrap_is_safe() -> None:
    config = bootstrap_config("secret-value")
    assert "enable: false" in config
    assert "MATCH,DIRECT" in config
    assert "127.0.0.1:9090" in config
    assert "secret-value" in config
    unit = systemd_unit()
    assert "CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE" in unit
    assert "DeviceAllow=/dev/net/tun rw" in unit
