import pytest
from nextgateway.services.subscription_fetch import SubscriptionFetchError, _validate_url


def test_subscription_fetch_rejects_non_https() -> None:
    with pytest.raises(SubscriptionFetchError, match="HTTPS"):
        _validate_url("http://example.com/subscription")


def test_subscription_fetch_rejects_private_destination(monkeypatch) -> None:
    monkeypatch.setattr(
        "nextgateway.services.subscription_fetch.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("192.168.1.2", 443))],
    )
    with pytest.raises(SubscriptionFetchError, match="non-public"):
        _validate_url("https://internal.example/subscription")
