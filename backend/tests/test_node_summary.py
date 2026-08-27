from nextgateway.models import Node
from nextgateway.schemas import NodeSummary


def test_node_summary_derives_transport_and_security() -> None:
    node = Node(
        id="node-1",
        name="Example",
        enabled=True,
        protocol="vless",
        server="example.com",
        port=443,
        source="manual",
        fingerprint="fingerprint",
        transport={"type": "grpc"},
        tls={"security": "reality"},
    )

    summary = NodeSummary.model_validate(node)

    assert summary.transport_type == "grpc"
    assert summary.security == "reality"


def test_hysteria_summary_uses_protocol_defaults() -> None:
    node = Node(
        id="node-2",
        name="Example",
        enabled=True,
        protocol="hysteria2",
        server="example.com",
        port=443,
        source="manual",
        fingerprint="fingerprint-2",
        transport={},
        tls={},
    )

    summary = NodeSummary.model_validate(node)

    assert summary.transport_type == "udp"
    assert summary.security == "tls"


def test_node_summary_labels_mlkem_without_exposing_encryption_value() -> None:
    node = Node(
        id="node-3",
        name="Example",
        enabled=True,
        protocol="vless",
        server="example.com",
        port=443,
        source="manual",
        fingerprint="fingerprint-3",
        credentials={"encryption": "mlkem768x25519plus.native.0rtt-secret-material"},
        transport={"type": "xhttp"},
        tls={"security": "none"},
    )

    summary = NodeSummary.model_validate(node)

    assert summary.security == "ml-kem-768"
    assert "secret" not in summary.model_dump_json()
