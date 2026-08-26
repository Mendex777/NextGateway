import hashlib
import ipaddress
import json
import uuid
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from ..schemas import NodeCreate


class VlessParseError(ValueError):
    pass


def _one(params: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = params.get(key)
    return values[-1] if values else default


def _host(value: str | None) -> str:
    if not value:
        raise VlessParseError("VLESS URI is missing a server")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        if len(value) > 255 or any(not part for part in value.split(".")):
            raise VlessParseError("VLESS server is invalid") from None
        return value.lower()


def node_fingerprint(node: NodeCreate) -> str:
    stable = json.dumps(
        {
            "name": node.name,
            "protocol": node.protocol.lower(),
            "server": node.server.lower(),
            "port": node.port,
            "credentials": node.credentials,
            "transport": node.transport,
            "tls": node.tls,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(stable.encode()).hexdigest()


def parse_vless_uri(uri: str) -> NodeCreate:
    try:
        parsed = urlsplit(uri.strip())
    except ValueError as exc:
        raise VlessParseError(f"Invalid VLESS URI: {exc}") from None
    if parsed.scheme.lower() != "vless":
        raise VlessParseError("URI scheme must be vless")
    try:
        user_id = str(uuid.UUID(unquote(parsed.username or "")))
    except ValueError:
        raise VlessParseError("VLESS URI contains an invalid UUID") from None
    try:
        port = parsed.port
    except ValueError:
        raise VlessParseError("VLESS URI contains an invalid port") from None
    if port is None:
        raise VlessParseError("VLESS URI is missing a port")

    params = parse_qs(parsed.query, keep_blank_values=True)
    transport_type = (_one(params, "type", "tcp") or "tcp").lower()
    if transport_type == "raw":
        transport_type = "tcp"
    if transport_type not in {"tcp", "ws", "grpc", "xhttp"}:
        raise VlessParseError(f"Unsupported VLESS transport: {transport_type}")
    security = (_one(params, "security", "none") or "none").lower()
    if security not in {"none", "tls", "reality"}:
        raise VlessParseError(f"Unsupported VLESS security: {security}")

    transport: dict[str, object] = {"type": transport_type}
    transport_fields = (
        ("path", "path"),
        ("host", "host"),
        ("serviceName", "service_name"),
        ("authority", "authority"),
        ("mode", "mode"),
        ("x_padding_bytes", "x_padding_bytes"),
    )
    for source_key, target_key in transport_fields:
        value = _one(params, source_key)
        if value:
            transport[target_key] = value

    tls: dict[str, object] = {"security": security}
    for source_key, target_key in (
        ("sni", "server_name"), ("fp", "client_fingerprint"),
        ("pbk", "public_key"), ("sid", "short_id"),
        ("spx", "spider_x"), ("pqv", "mldsa65_verify"),
    ):
        value = _one(params, source_key)
        if value:
            tls[target_key] = value
    if alpn := _one(params, "alpn"):
        tls["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]

    name = unquote(parsed.fragment).strip() or f"{parsed.hostname}:{port}"
    return NodeCreate(
        name=name,
        protocol="vless",
        server=_host(parsed.hostname),
        port=port,
        credentials={
            "uuid": user_id,
            "flow": _one(params, "flow"),
            "encryption": _one(params, "encryption", "none"),
        },
        transport=transport,
        tls=tls,
    )


def build_vless_uri(node) -> str:
    if node.protocol != "vless":
        raise VlessParseError("Only VLESS nodes can be shared")
    params: list[tuple[str, str]] = []
    encryption = node.credentials.get("encryption", "none") or "none"
    params.append(("encryption", str(encryption)))
    if flow := node.credentials.get("flow"):
        params.append(("flow", str(flow)))
    security = str(node.tls.get("security", "none"))
    params.append(("security", security))
    for source, target in (
        ("server_name", "sni"), ("client_fingerprint", "fp"),
        ("public_key", "pbk"), ("short_id", "sid"),
        ("spider_x", "spx"), ("mldsa65_verify", "pqv"),
    ):
        if value := node.tls.get(source):
            params.append((target, str(value)))
    if alpn := node.tls.get("alpn"):
        params.append(("alpn", ",".join(str(item) for item in alpn)))
    transport_type = str(node.transport.get("type", "tcp"))
    params.append(("type", transport_type))
    for source, target in (
        ("path", "path"), ("host", "host"),
        ("service_name", "serviceName"), ("authority", "authority"),
        ("mode", "mode"), ("x_padding_bytes", "x_padding_bytes"),
    ):
        if source in node.transport:
            params.append((target, str(node.transport[source])))
    host = f"[{node.server}]" if ":" in node.server else node.server
    user_id = quote(str(node.credentials["uuid"]), safe="")
    fragment = quote(node.name, safe="")
    return f"vless://{user_id}@{host}:{node.port}?{urlencode(params)}#{fragment}"
