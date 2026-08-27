from types import SimpleNamespace

import pytest
from nextgateway.services.vless import (
    VlessParseError,
    build_vless_uri,
    node_fingerprint,
    parse_vless_uri,
)


def test_parse_vless_reality_xhttp() -> None:
    node = parse_vless_uri(
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?encryption=none&security=reality&sni=www.microsoft.com&fp=chrome"
        "&pbk=publickey&sid=abcd&spx=%2Fcrawler&pqv=verifykey"
        "&type=xhttp&path=%2Fapi#DE-01"
    )
    assert node.name == "DE-01"
    assert node.server == "example.com"
    assert node.transport == {"type": "xhttp", "path": "/api"}
    assert node.tls["security"] == "reality"
    assert node.tls["spider_x"] == "/crawler"
    assert node.tls["mldsa65_verify"] == "verifykey"
    assert len(node_fingerprint(node)) == 64


def test_parse_vless_xhttp_compatibility_fields() -> None:
    node = parse_vless_uri(
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?encryption=mlkem-secret&type=xhttp&path=%2Fx&mode=auto"
        "&x_padding_bytes=100-1000&alpn=h2#XHTTP"
    )
    assert node.credentials["encryption"] == "mlkem-secret"
    assert node.transport["mode"] == "auto"
    assert node.transport["x_padding_bytes"] == "100-1000"
    assert node.tls["alpn"] == ["h2"]


def test_grpc_preserves_empty_provider_service_name() -> None:
    node = parse_vless_uri(
        "vless://11111111-1111-4111-8111-111111111111@example.com:443?type=grpc&serviceName=#GRPC"
    )
    assert "service_name" not in node.transport


def test_build_shareable_vless_uri_round_trips() -> None:
    original = parse_vless_uri(
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?encryption=none&security=reality&sni=example.org&fp=chrome"
        "&pbk=public&sid=abcd&spx=%2Ftest&type=grpc&serviceName=grpc#🇳🇱%20Node"
    )
    restored = parse_vless_uri(build_vless_uri(SimpleNamespace(**original.model_dump())))
    assert restored.name == original.name
    assert restored.credentials == original.credentials
    assert restored.transport == original.transport
    assert restored.tls == original.tls


@pytest.mark.parametrize(
    "uri,message",
    [
        ("https://example.com", "scheme"),
        ("vless://bad@example.com:443", "UUID"),
        ("vless://11111111-1111-4111-8111-111111111111@example.com", "port"),
        ("vless://11111111-1111-4111-8111-111111111111@example.com:443?type=kcp", "transport"),
    ],
)
def test_reject_invalid_vless(uri: str, message: str) -> None:
    with pytest.raises(VlessParseError, match=message):
        parse_vless_uri(uri)
