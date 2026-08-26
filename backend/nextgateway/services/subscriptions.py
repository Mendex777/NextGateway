import base64
import binascii
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from ..models import Node, SubscriptionNode
from ..schemas import NodeCreate
from .hysteria2 import parse_hysteria2_uri
from .vless import VlessParseError, node_fingerprint, parse_vless_uri


class SubscriptionParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSubscription:
    format: str
    nodes: list
    protocol_counts: dict[str, int]
    unsupported_count: int
    invalid_count: int
    sha256: str


@dataclass(frozen=True)
class SubscriptionDiff:
    added: int
    updated: int
    unchanged: int
    missing: int


def _decode_text(content: bytes) -> tuple[str, str]:
    stripped = content.strip()
    try:
        plain = stripped.decode("utf-8-sig")
    except UnicodeDecodeError:
        plain = ""
    supported_prefixes = ("vless://", "hysteria2://", "hy2://", "trojan://")
    if any(line.strip().startswith(supported_prefixes) for line in plain.splitlines()):
        return plain, "uri-list"
    try:
        decoded = base64.b64decode(stripped + b"=" * ((-len(stripped)) % 4), validate=True)
        text = decoded.decode("utf-8-sig")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise SubscriptionParseError("Unsupported subscription format") from exc
    return text, "base64-uri-list"


def _xray_vless_node(profile: dict) -> NodeCreate:
    outbound = next(
        item
        for item in profile.get("outbounds", [])
        if item.get("protocol") == "vless" and not str(item.get("tag", "")).startswith("cand-")
    )
    vnext = outbound["settings"]["vnext"][0]
    user = vnext["users"][0]
    stream = outbound.get("streamSettings", {})
    network = stream.get("network", "tcp")
    transport: dict = {"type": network}
    if network == "grpc":
        grpc = stream.get("grpcSettings", {})
        if grpc.get("serviceName"):
            transport["service_name"] = grpc["serviceName"]
        if grpc.get("mode"):
            transport["mode"] = grpc["mode"]
    elif network == "ws":
        ws = stream.get("wsSettings", {})
        if ws.get("path"):
            transport["path"] = ws["path"]
        host = (ws.get("headers") or {}).get("Host")
        if host:
            transport["host"] = host
    security = stream.get("security", "none")
    security_settings = stream.get(
        "realitySettings" if security == "reality" else "tlsSettings", {}
    )
    tls: dict = {"security": security}
    field_map = {
        "serverName": "server_name",
        "fingerprint": "client_fingerprint",
        "publicKey": "public_key",
        "shortId": "short_id",
        "spiderX": "spider_x",
        "alpn": "alpn",
        "pinnedPeerCertSha256": "certificate_fingerprint",
    }
    for source, target in field_map.items():
        if security_settings.get(source):
            tls[target] = security_settings[source]
    return NodeCreate(
        name=str(profile.get("remarks") or outbound.get("tag") or "VLESS")[:255],
        protocol="vless",
        server=str(vnext["address"]),
        port=int(vnext["port"]),
        credentials={
            "uuid": user["id"],
            "encryption": user.get("encryption", "none"),
            **({"flow": user["flow"]} if user.get("flow") else {}),
        },
        transport=transport,
        tls=tls,
    )


def _parse_xray_json(content: bytes) -> ParsedSubscription | None:
    try:
        document = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    profiles = document if isinstance(document, list) else [document]
    if not all(isinstance(profile, dict) for profile in profiles):
        return None
    nodes = []
    fingerprints: set[str] = set()
    invalid = unsupported = 0
    for profile in profiles:
        eligible = [
            item
            for item in profile.get("outbounds", [])
            if item.get("protocol") == "vless" and not str(item.get("tag", "")).startswith("cand-")
        ]
        if not eligible:
            unsupported += 1
            continue
        try:
            node = _xray_vless_node(profile)
            fingerprint = node_fingerprint(node)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            nodes.append(node)
        except (KeyError, IndexError, TypeError, ValueError):
            invalid += 1
    if not nodes:
        raise SubscriptionParseError("Xray JSON contains no supported VLESS outbounds")
    return ParsedSubscription(
        format="xray-json-array" if isinstance(document, list) else "xray-json",
        nodes=nodes,
        protocol_counts={"vless": len(nodes)},
        unsupported_count=unsupported,
        invalid_count=invalid,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def parse_subscription(content: bytes) -> ParsedSubscription:
    if parsed_json := _parse_xray_json(content):
        return parsed_json
    text, detected_format = _decode_text(content)
    nodes = []
    seen_fingerprints: set[str] = set()
    counts: Counter[str] = Counter()
    unsupported = 0
    invalid = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        scheme = line.partition("://")[0].lower()
        counts[scheme] += 1
        if scheme not in {"vless", "hysteria2", "hy2"}:
            unsupported += 1
            continue
        try:
            parser = parse_vless_uri if scheme == "vless" else parse_hysteria2_uri
            node = parser(line)
            fingerprint = node_fingerprint(node)
            if fingerprint in seen_fingerprints:
                continue
            seen_fingerprints.add(fingerprint)
            nodes.append(node)
        except VlessParseError:
            invalid += 1
    if not nodes and not unsupported:
        raise SubscriptionParseError("Subscription contains no supported URI entries")
    return ParsedSubscription(
        format=detected_format,
        nodes=nodes,
        protocol_counts=dict(counts),
        unsupported_count=unsupported,
        invalid_count=invalid,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def sync_nodes(session: Session, parsed: ParsedSubscription, source_ref: str) -> SubscriptionDiff:
    linked_nodes = list(
        session.scalars(
            select(Node)
            .join(SubscriptionNode, SubscriptionNode.node_id == Node.id)
            .where(SubscriptionNode.subscription_id == source_ref)
            .order_by(SubscriptionNode.position)
        )
    )
    existing = {node.fingerprint: node for node in linked_nodes}
    existing_by_identity: dict[tuple[str, str, str, int], list[Node]] = {}
    for node in linked_nodes:
        source_name = re.sub(r" \(\d+\)$", "", node.name)
        key = (source_name, node.protocol, node.server.lower(), node.port)
        existing_by_identity.setdefault(key, []).append(node)
    global_nodes = {node.fingerprint: node for node in session.scalars(select(Node))}
    used_names = {node.name for node in global_nodes.values()}
    links_by_node = {
        link.node_id: link
        for link in session.scalars(
            select(SubscriptionNode).where(SubscriptionNode.subscription_id == source_ref)
        )
    }
    incoming: set[str] = set()
    claimed_existing: set[str] = set()
    added = updated = unchanged = 0
    for position, payload in enumerate(parsed.nodes):
        fingerprint = node_fingerprint(payload)
        incoming.add(fingerprint)
        current = existing.get(fingerprint) or global_nodes.get(fingerprint)
        if current is None:
            identity = (payload.name, payload.protocol, payload.server.lower(), payload.port)
            current = next(
                (
                    node
                    for node in existing_by_identity.get(identity, [])
                    if node.id not in claimed_existing
                ),
                None,
            )
            if current is not None:
                global_nodes.pop(current.fingerprint, None)
                current.fingerprint = fingerprint
                global_nodes[fingerprint] = current
        if current is None:
            desired_name = payload.name
            candidate_name = desired_name
            suffix = 2
            while candidate_name in used_names:
                marker = f" ({suffix})"
                candidate_name = f"{desired_name[: 255 - len(marker)]}{marker}"
                suffix += 1
            current = Node(
                **{**payload.model_dump(exclude={"source"}), "name": candidate_name},
                source="subscription",
                source_ref=source_ref,
                fingerprint=fingerprint,
            )
            session.add(current)
            session.flush()
            global_nodes[fingerprint] = current
            used_names.add(candidate_name)
            added += 1
        else:
            claimed_existing.add(current.id)
            used_names.discard(current.name)
            desired_name = payload.name
            candidate_name = desired_name
            suffix = 2
            while candidate_name in used_names:
                marker = f" ({suffix})"
                candidate_name = f"{desired_name[: 255 - len(marker)]}{marker}"
                suffix += 1
            current.name = candidate_name
            used_names.add(candidate_name)
            changed = any(
                getattr(current, field) != getattr(payload, field)
                for field in ("server", "port", "credentials", "transport", "tls")
            )
            if changed:
                current.server = payload.server
                current.port = payload.port
                current.credentials = payload.credentials
                current.transport = payload.transport
                current.tls = payload.tls
                updated += 1
            else:
                unchanged += 1
        link = links_by_node.get(current.id)
        if link is None:
            link = SubscriptionNode(
                subscription_id=source_ref, node_id=current.id, position=position
            )
            session.add(link)
            links_by_node[current.id] = link
        else:
            link.position = position
    missing = len(set(existing) - incoming)
    stale_ids = [
        node.id
        for node in linked_nodes
        if node.id not in claimed_existing and node.fingerprint not in incoming
    ]
    if stale_ids:
        session.execute(
            delete(SubscriptionNode).where(
                SubscriptionNode.subscription_id == source_ref,
                SubscriptionNode.node_id.in_(stale_ids),
            )
        )
        session.execute(
            delete(Node).where(
                Node.id.in_(stale_ids),
                Node.source == "subscription",
                ~exists().where(SubscriptionNode.node_id == Node.id),
            )
        )
    session.commit()
    return SubscriptionDiff(added, updated, unchanged, missing)
