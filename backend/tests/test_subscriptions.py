import base64
import json
from pathlib import Path

from nextgateway.db import Base
from nextgateway.models import Node, Subscription, SubscriptionNode
from nextgateway.services.hysteria2 import build_hysteria2_uri, parse_hysteria2_uri
from nextgateway.services.subscriptions import parse_subscription, sync_nodes
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


def test_parse_base64_vless_subscription() -> None:
    uri = (
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?security=reality&type=xhttp&pbk=key&sid=abcd#DE-01"
    )
    parsed = parse_subscription(base64.b64encode(uri.encode()))
    assert parsed.format == "base64-uri-list"
    assert len(parsed.nodes) == 1
    assert parsed.protocol_counts == {"vless": 1}
    assert parsed.invalid_count == 0


def test_parse_subscription_with_hysteria2() -> None:
    content = (
        "hysteria2://password@example.com:443?obfs=salamander&"
        "obfs-password=mask&sni=example.com&alpn=h3#HY2"
    )
    parsed = parse_subscription(content.encode())
    assert len(parsed.nodes) == 1
    assert parsed.nodes[0].protocol == "hysteria2"
    assert parsed.nodes[0].credentials["password"] == "password"


def test_build_hysteria2_share_uri_round_trips() -> None:
    from types import SimpleNamespace

    original = parse_hysteria2_uri(
        "hysteria2://password@example.com:443?obfs=salamander&"
        "obfs-password=mask&sni=example.com&alpn=h3#🇳🇱%20HY2"
    )
    restored = parse_hysteria2_uri(build_hysteria2_uri(SimpleNamespace(**original.model_dump())))
    assert restored.name == original.name
    assert restored.credentials == original.credentials
    assert restored.transport == original.transport
    assert restored.tls == original.tls


def test_same_node_can_belong_to_multiple_subscriptions(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'subscriptions.db'}")
    Base.metadata.create_all(engine)
    uri = (
        "vless://11111111-1111-4111-8111-111111111111@example.com:443"
        "?security=reality&type=xhttp&pbk=key&sid=abcd#DE-01"
    )
    parsed = parse_subscription(base64.b64encode(uri.encode()))
    with Session(engine) as session:
        session.add_all(
            [
                Subscription(id="sub-1", name="One", secret_ref="/one"),
                Subscription(id="sub-2", name="Two", secret_ref="/two"),
            ]
        )
        session.commit()
        sync_nodes(session, parsed, "sub-1")
        sync_nodes(session, parsed, "sub-2")
        assert session.scalar(select(func.count()).select_from(SubscriptionNode)) == 2


def test_sync_preserves_provider_order(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'order.db'}")
    Base.metadata.create_all(engine)
    content = "\n".join(
        [
            "vless://11111111-1111-4111-8111-111111111111@z.example:443?type=tcp#First",
            "vless://22222222-2222-4222-8222-222222222222@a.example:443?type=tcp#Second",
        ]
    )
    with Session(engine) as session:
        session.add(Subscription(id="sub", name="Order", secret_ref="/order"))
        session.commit()
        sync_nodes(session, parse_subscription(content.encode()), "sub")
        links = list(
            session.scalars(
                select(SubscriptionNode)
                .where(SubscriptionNode.subscription_id == "sub")
                .order_by(SubscriptionNode.position)
            )
        )
        assert [link.position for link in links] == [0, 1]


def test_parse_subscription_deduplicates_nodes_preserving_first_entry() -> None:
    first = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls#First"
    duplicate = first

    parsed = parse_subscription(f"{first}\n{duplicate}\n".encode())

    assert len(parsed.nodes) == 1
    assert parsed.nodes[0].name == "First"


def test_parse_xray_json_array_ignores_auto_candidates() -> None:
    content = json.dumps(
        [
            {
                "remarks": "Auto",
                "outbounds": [
                    {
                        "tag": "cand-01",
                        "protocol": "vless",
                        "settings": {
                            "vnext": [
                                {
                                    "address": "auto.example",
                                    "port": 443,
                                    "users": [{"id": "11111111-1111-4111-8111-111111111111"}],
                                }
                            ]
                        },
                    }
                ],
            },
            {
                "remarks": "🇳🇱 Node",
                "outbounds": [
                    {
                        "tag": "proxy",
                        "protocol": "vless",
                        "settings": {
                            "vnext": [
                                {
                                    "address": "node.example",
                                    "port": 443,
                                    "users": [
                                        {
                                            "id": "22222222-2222-4222-8222-222222222222",
                                            "encryption": "none",
                                        }
                                    ],
                                }
                            ]
                        },
                        "streamSettings": {
                            "network": "grpc",
                            "security": "tls",
                            "grpcSettings": {"serviceName": "service", "mode": "gun"},
                            "tlsSettings": {
                                "serverName": "sni.example",
                                "fingerprint": "qq",
                                "pinnedPeerCertSha256": "AA:BB",
                            },
                        },
                    },
                    {"tag": "direct", "protocol": "freedom"},
                ],
            },
        ]
    ).encode()

    parsed = parse_subscription(content)

    assert parsed.format == "xray-json-array"
    assert len(parsed.nodes) == 1
    node = parsed.nodes[0]
    assert node.name == "🇳🇱 Node"
    assert node.transport == {"type": "grpc", "service_name": "service", "mode": "gun"}
    assert node.tls["client_fingerprint"] == "qq"
    assert node.tls["certificate_fingerprint"] == "AA:BB"


def test_parse_subscription_treats_raw_transport_as_tcp() -> None:
    uri = "vless://11111111-1111-1111-1111-111111111111@example.com:443?type=raw#Raw"

    parsed = parse_subscription(uri.encode())

    assert parsed.nodes[0].transport["type"] == "tcp"


def test_subscription_keeps_nodes_with_different_tls_fingerprints() -> None:
    base = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=reality&type=grpc"
    parsed = parse_subscription(f"{base}&fp=chrome#Chrome\n{base}&fp=firefox#Firefox".encode())

    assert [node.name for node in parsed.nodes] == ["Chrome", "Firefox"]


def test_sync_restores_source_name_after_temporary_suffix(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'restore-name.db'}")
    Base.metadata.create_all(engine)
    uri = "vless://11111111-1111-1111-1111-111111111111@example.com:443#Original"
    with Session(engine) as session:
        session.add(Subscription(id="sub", name="Sub", secret_ref="secret"))
        session.commit()
        parsed = parse_subscription(uri.encode())
        sync_nodes(session, parsed, "sub")
        link = session.scalar(
            select(SubscriptionNode).where(SubscriptionNode.subscription_id == "sub")
        )
        stored = session.get(Node, link.node_id)
        stored.name = "Original (2)"
        session.commit()

        sync_nodes(session, parsed, "sub")

        assert stored.name == "Original"


def test_sync_updates_volatile_tls_fingerprint_in_place(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'volatile-fp.db'}")
    Base.metadata.create_all(engine)
    base = "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=reality&type=grpc"
    with Session(engine) as session:
        session.add(Subscription(id="sub", name="Sub", secret_ref="secret"))
        session.commit()
        sync_nodes(session, parse_subscription(f"{base}&fp=chrome#Original".encode()), "sub")
        original = session.scalar(select(Node))
        original_id = original.id

        sync_nodes(session, parse_subscription(f"{base}&fp=firefox#Original".encode()), "sub")

        nodes = list(session.scalars(select(Node)))
        assert len(nodes) == 1
        assert nodes[0].id == original_id
        assert nodes[0].name == "Original"
        assert nodes[0].tls["client_fingerprint"] == "firefox"
