from datetime import UTC, datetime

from nextgateway.services.subscription_metadata import parse_subscription_metadata


def test_parses_standard_subscription_headers() -> None:
    metadata = parse_subscription_metadata(
        {
            "profile-title": "Example VPN",
            "subscription-userinfo": "upload=10; download=20; total=100; expire=1893456000",
            "profile-update-interval": "6",
            "profile-announcement": "Service message",
            "support-url": "https://example.com/support",
        }
    )
    assert metadata.remote_name == "Example VPN"
    assert metadata.upload_bytes == 10
    assert metadata.download_bytes == 20
    assert metadata.total_bytes == 100
    assert metadata.expires_at == datetime.fromtimestamp(1893456000, UTC)
    assert metadata.update_interval == 21600
    assert metadata.announcement == "Service message"
