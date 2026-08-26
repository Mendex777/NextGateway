from pathlib import Path

from nextgateway.services.subscription_source import (
    read_subscription_source,
    write_subscription_source,
)


def test_subscription_source_round_trips_device_headers(tmp_path: Path) -> None:
    path = tmp_path / "source.url"
    headers = {
        "User-Agent": "v2raytun/android",
        "X-HWID": "device-id",
        "X-Device-OS": "Android",
    }

    write_subscription_source(path, "https://example.com/sub", headers)
    restored = read_subscription_source(path)

    assert restored.url == "https://example.com/sub"
    assert restored.headers == headers


def test_subscription_source_reads_legacy_plain_url(tmp_path: Path) -> None:
    path = tmp_path / "legacy.url"
    path.write_text("https://example.com/legacy\n")

    restored = read_subscription_source(path)

    assert restored.url == "https://example.com/legacy"
    assert restored.headers == {}
