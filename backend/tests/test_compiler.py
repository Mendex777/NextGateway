from types import SimpleNamespace

import pytest
from nextgateway.services.compiler import CompileError, CompileInput, compile_mihomo


def node(node_id: str = "n1") -> SimpleNamespace:
    return SimpleNamespace(
        id=node_id,
        name="DE-01",
        enabled=True,
        protocol="vless",
        server="example.com",
        port=443,
        credentials={
            "uuid": "11111111-1111-4111-8111-111111111111",
            "flow": None,
            "encryption": "mlkem-secret",
        },
        transport={
            "type": "xhttp", "path": "/api", "mode": "auto",
            "x_padding_bytes": "100-1000",
        },
        tls={
            "security": "reality",
            "server_name": "www.microsoft.com",
            "client_fingerprint": "chrome",
            "public_key": "publickey",
            "short_id": "abcd",
            "spider_x": "/crawler",
        },
    )


def test_compile_minimal_configuration() -> None:
    group = SimpleNamespace(
        name="VPN",
        type="select",
        enabled=True,
        members=[SimpleNamespace(node_id="n1", position=0)],
        health_url=None,
        interval=None,
        tolerance=None,
    )
    rules = [SimpleNamespace(enabled=True, position=999, type="MATCH", value=None, target="VPN")]
    result = compile_mihomo(CompileInput(nodes=[node()], groups=[group], rules=rules))
    assert result["tun"]["auto-redirect"] is True
    assert result["dns"]["listen"] == "192.168.1.84:53"
    assert result["proxy-groups"][0]["proxies"] == ["DE-01"]
    assert result["rules"] == ["MATCH,VPN"]
    assert result["proxies"][0]["reality-opts"]["public-key"] == "publickey"
    assert result["proxies"][0]["reality-opts"]["spider-x"] == "/crawler"
    assert result["proxies"][0]["encryption"] == "mlkem-secret"
    assert result["proxies"][0]["xhttp-opts"]["mode"] == "auto"


def test_compile_hysteria2() -> None:
    proxy = SimpleNamespace(
        id="hy2", name="HY2", enabled=True, protocol="hysteria2", server="example.com",
        port=443, credentials={"password": "secret"},
        transport={"obfs": "salamander", "obfs_password": "mask"},
        tls={"server_name": "example.com", "alpn": ["h3"], "skip_cert_verify": False},
    )
    result = compile_mihomo(CompileInput(nodes=[proxy], groups=[], rules=[SimpleNamespace(
        enabled=True, position=999, type="MATCH", value=None, target="HY2"
    )]))
    assert result["proxies"][0]["type"] == "hysteria2"
    assert result["proxies"][0]["obfs"] == "salamander"
    assert result["rules"] == ["MATCH,HY2"]


def test_compiler_requires_final_match() -> None:
    rule = SimpleNamespace(
        enabled=True, position=10, type="DOMAIN-SUFFIX", value="example.com", target="DIRECT"
    )
    with pytest.raises(CompileError, match="last enabled"):
        compile_mihomo(CompileInput(nodes=[node()], groups=[], rules=[rule]))
