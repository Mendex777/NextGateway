from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from ..schemas import NodeCreate
from .vless import VlessParseError, _host, _one


def parse_hysteria2_uri(uri: str) -> NodeCreate:
    try:
        parsed = urlsplit(uri.strip())
    except ValueError as exc:
        raise VlessParseError(f"Invalid Hysteria2 URI: {exc}") from None
    if parsed.scheme.lower() not in {"hysteria2", "hy2"}:
        raise VlessParseError("URI scheme must be hysteria2 or hy2")
    password = unquote(parsed.username or "")
    if not password:
        raise VlessParseError("Hysteria2 URI is missing a password")
    try:
        port = parsed.port
    except ValueError:
        raise VlessParseError("Hysteria2 URI contains an invalid port") from None
    if port is None:
        raise VlessParseError("Hysteria2 URI is missing a port")
    params = parse_qs(parsed.query, keep_blank_values=True)
    transport: dict[str, object] = {}
    for source, target in (
        ("obfs", "obfs"),
        ("obfs-password", "obfs_password"),
        ("ports", "ports"),
        ("mport", "ports"),
        ("hop-interval", "hop_interval"),
        ("up", "up"),
        ("down", "down"),
    ):
        if value := _one(params, source):
            transport[target] = value
    tls: dict[str, object] = {"security": "tls"}
    if sni := _one(params, "sni"):
        tls["server_name"] = sni
    if alpn := _one(params, "alpn"):
        tls["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]
    insecure = (_one(params, "insecure", "0") or "0").lower()
    tls["skip_cert_verify"] = insecure in {"1", "true", "yes"}
    name = unquote(parsed.fragment).strip() or f"{parsed.hostname}:{port}"
    return NodeCreate(
        name=name,
        protocol="hysteria2",
        server=_host(parsed.hostname),
        port=port,
        credentials={"password": password},
        transport=transport,
        tls=tls,
    )


def build_hysteria2_uri(node) -> str:
    if node.protocol != "hysteria2":
        raise VlessParseError("Only Hysteria2 nodes can use this exporter")
    params: list[tuple[str, str]] = []
    for source, target in (
        ("obfs", "obfs"), ("obfs_password", "obfs-password"),
        ("ports", "ports"), ("hop_interval", "hop-interval"),
        ("up", "up"), ("down", "down"),
    ):
        if value := node.transport.get(source):
            params.append((target, str(value)))
    if value := node.tls.get("server_name"):
        params.append(("sni", str(value)))
    if alpn := node.tls.get("alpn"):
        params.append(("alpn", ",".join(str(item) for item in alpn)))
    if node.tls.get("skip_cert_verify"):
        params.append(("insecure", "1"))
    host = f"[{node.server}]" if ":" in node.server else node.server
    password = quote(str(node.credentials["password"]), safe="")
    fragment = quote(node.name, safe="")
    query = urlencode(params)
    suffix = f"?{query}" if query else ""
    return f"hysteria2://{password}@{host}:{node.port}{suffix}#{fragment}"
