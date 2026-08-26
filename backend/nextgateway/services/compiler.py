from dataclasses import dataclass
from typing import Any

import yaml

from ..models import Node, ProxyGroup, RoutingRule


class CompileError(ValueError):
    pass


@dataclass(frozen=True)
class CompileInput:
    nodes: list[Node]
    groups: list[ProxyGroup]
    rules: list[RoutingRule]
    interface_name: str = "ens18"
    lan_address: str = "192.168.1.84"
    local_networks: tuple[str, ...] = ("192.168.1.0/24",)
    controller_address: str = "127.0.0.1"


def _compile_node(node: Node) -> dict[str, Any]:
    if node.protocol == "hysteria2":
        result: dict[str, Any] = {
            "name": node.name,
            "type": "hysteria2",
            "server": node.server,
            "port": node.port,
            "password": node.credentials["password"],
        }
        for source, target in (
            ("ports", "ports"),
            ("hop_interval", "hop-interval"),
            ("up", "up"),
            ("down", "down"),
            ("obfs", "obfs"),
            ("obfs_password", "obfs-password"),
        ):
            if value := node.transport.get(source):
                result[target] = value
        if server_name := node.tls.get("server_name"):
            result["sni"] = server_name
        if alpn := node.tls.get("alpn"):
            result["alpn"] = alpn
        result["skip-cert-verify"] = bool(node.tls.get("skip_cert_verify", False))
        return result
    if node.protocol != "vless":
        raise CompileError(f"Unsupported node protocol: {node.protocol}")
    result: dict[str, Any] = {
        "name": node.name,
        "type": "vless",
        "server": node.server,
        "port": node.port,
        "uuid": node.credentials["uuid"],
        "udp": True,
        "network": node.transport.get("type", "tcp"),
    }
    if flow := node.credentials.get("flow"):
        result["flow"] = flow
    encryption = node.credentials.get("encryption")
    result["encryption"] = "" if encryption in {None, "none"} else encryption
    transport_type = node.transport.get("type", "tcp")
    if transport_type in {"ws", "xhttp"}:
        options: dict[str, Any] = {}
        if path := node.transport.get("path"):
            options["path"] = path
        if host := node.transport.get("host"):
            if transport_type == "ws":
                options["headers"] = {"Host": host}
            else:
                options["host"] = host
        if transport_type == "xhttp":
            if mode := node.transport.get("mode"):
                options["mode"] = mode
            if padding := node.transport.get("x_padding_bytes"):
                options["x-padding-bytes"] = padding
        result[f"{transport_type}-opts"] = options
    elif transport_type == "grpc":
        result["grpc-opts"] = {
            "grpc-service-name": node.transport.get("service_name", "")
        }

    security = node.tls.get("security", "none")
    if security in {"tls", "reality"}:
        result["tls"] = True
        if server_name := node.tls.get("server_name"):
            result["servername"] = server_name
        if fingerprint := node.tls.get("client_fingerprint"):
            result["client-fingerprint"] = fingerprint
        if alpn := node.tls.get("alpn"):
            result["alpn"] = alpn
        if certificate_fingerprint := node.tls.get("certificate_fingerprint"):
            result["fingerprint"] = certificate_fingerprint
    if security == "reality":
        result["reality-opts"] = {
            "public-key": node.tls.get("public_key", ""),
            "short-id": node.tls.get("short_id", ""),
        }
        if spider_x := node.tls.get("spider_x"):
            result["reality-opts"]["spider-x"] = spider_x
    return result


def compile_mihomo(data: CompileInput) -> dict[str, Any]:
    nodes = [node for node in data.nodes if node.enabled]
    node_by_id = {node.id: node for node in nodes}
    names = [node.name for node in nodes]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise CompileError(f"Enabled node names must be unique: {', '.join(duplicates)}")

    groups: list[dict[str, Any]] = []
    group_names: set[str] = set()
    for group in data.groups:
        if not group.enabled:
            continue
        if group.name in group_names or group.name in names or group.name in {"DIRECT", "REJECT"}:
            raise CompileError(f"Duplicate or reserved group name: {group.name}")
        group_names.add(group.name)
        members = [
            node_by_id[item.node_id].name
            for item in group.members
            if item.node_id in node_by_id
        ]
        if not members:
            raise CompileError(f"Proxy group has no enabled nodes: {group.name}")
        compiled: dict[str, Any] = {"name": group.name, "type": group.type, "proxies": members}
        if group.type in {"url-test", "fallback"}:
            compiled["url"] = group.health_url or "https://www.gstatic.com/generate_204"
            compiled["interval"] = group.interval or 300
        if group.type == "url-test" and group.tolerance is not None:
            compiled["tolerance"] = group.tolerance
        groups.append(compiled)

    valid_targets = group_names | set(names) | {"DIRECT", "REJECT"}
    rules: list[str] = []
    enabled_rules = (rule for rule in data.rules if rule.enabled)
    for rule in sorted(enabled_rules, key=lambda item: item.position):
        if rule.target not in valid_targets:
            raise CompileError(f"Routing rule references an unknown target: {rule.target}")
        compiled_rule = (
            f"MATCH,{rule.target}"
            if rule.type == "MATCH"
            else f"{rule.type},{rule.value},{rule.target}"
        )
        rules.append(compiled_rule)
    if not rules or not rules[-1].startswith("MATCH,"):
        raise CompileError("The last enabled routing rule must be MATCH")

    return {
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "allow-lan": False,
        "find-process-mode": "off",
        "interface-name": data.interface_name,
        "external-controller": f"{data.controller_address}:9090",
        "tun": {
            "enable": True,
            "device": "mihomo",
            "stack": "mixed",
            "auto-route": True,
            "auto-redirect": True,
            "strict-route": True,
            "auto-detect-interface": False,
            "route-exclude-address": list(data.local_networks),
            "dns-hijack": ["any:53", "tcp://any:53"],
        },
        "dns": {
            "enable": True,
            "listen": f"{data.lan_address}:53",
            "ipv6": False,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "default-nameserver": ["1.1.1.1", "8.8.8.8"],
            "proxy-server-nameserver": ["1.1.1.1", "8.8.8.8"],
            "nameserver": ["https://1.1.1.1/dns-query"],
        },
        "proxies": [_compile_node(node) for node in nodes],
        "proxy-groups": groups,
        "rules": rules,
    }


def dump_mihomo_yaml(data: CompileInput) -> str:
    return yaml.safe_dump(compile_mihomo(data), allow_unicode=True, sort_keys=False)
