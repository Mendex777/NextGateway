import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SubscriptionSource:
    url: str
    headers: dict[str, str]


def read_subscription_source(path: Path) -> SubscriptionSource:
    raw = path.read_text().strip()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return SubscriptionSource(url=raw, headers={})
    if not isinstance(document, dict) or not isinstance(document.get("url"), str):
        return SubscriptionSource(url=raw, headers={})
    headers = document.get("headers", {})
    if not isinstance(headers, dict):
        headers = {}
    return SubscriptionSource(
        url=document["url"].strip(),
        headers={str(key): str(value) for key, value in headers.items() if value},
    )


def write_subscription_source(
    path: Path, url: str, headers: dict[str, str] | None = None
) -> None:
    document = {"version": 1, "url": url.strip(), "headers": headers or {}}
    path.write_text(json.dumps(document, ensure_ascii=False))
    path.chmod(0o600)
