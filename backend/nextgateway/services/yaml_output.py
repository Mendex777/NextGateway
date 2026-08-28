from typing import Any

import yaml


class QuotedString(str):
    """A string that must remain a string across different YAML parsers."""


class NextGatewayDumper(yaml.SafeDumper):
    pass


def _represent_quoted_string(dumper: yaml.SafeDumper, value: QuotedString) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"')


NextGatewayDumper.add_representer(QuotedString, _represent_quoted_string)


def quote_reality_short_ids(document: dict[str, Any]) -> None:
    """Keep exponent-like IDs such as ``1e10`` as strings in Go YAML parsers."""
    for proxy in document.get("proxies", []):
        if not isinstance(proxy, dict):
            continue
        reality = proxy.get("reality-opts")
        if isinstance(reality, dict) and isinstance(reality.get("short-id"), str):
            reality["short-id"] = QuotedString(reality["short-id"])


def dump_mihomo_document(document: dict[str, Any]) -> str:
    quote_reality_short_ids(document)
    return yaml.dump(
        document,
        Dumper=NextGatewayDumper,
        allow_unicode=True,
        sort_keys=False,
    )
