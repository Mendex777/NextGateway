import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote


@dataclass(frozen=True)
class SubscriptionMetadata:
    remote_name: str | None = None
    upload_bytes: int | None = None
    download_bytes: int | None = None
    total_bytes: int | None = None
    expires_at: datetime | None = None
    announcement: str | None = None
    support_url: str | None = None
    web_url: str | None = None
    update_interval: int | None = None


def _text(value: str | None) -> str | None:
    if not value:
        return None
    value = unquote(value).strip()
    if value.lower().startswith("base64:"):
        try:
            value = base64.b64decode(value[7:] + "===").decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
    return value[:4096]


def _integer(value: str | None) -> int | None:
    try:
        result = int(value or "")
    except ValueError:
        return None
    return max(result, 0)


def parse_subscription_metadata(headers: dict[str, str]) -> SubscriptionMetadata:
    userinfo: dict[str, str] = {}
    for part in headers.get("subscription-userinfo", "").split(";"):
        key, separator, value = part.strip().partition("=")
        if separator:
            userinfo[key.lower()] = value.strip()
    expires = _integer(userinfo.get("expire"))
    interval_hours = _integer(headers.get("profile-update-interval"))
    announcement = headers.get("profile-announcement") or headers.get("announce")
    return SubscriptionMetadata(
        remote_name=_text(headers.get("profile-title")),
        upload_bytes=_integer(userinfo.get("upload")),
        download_bytes=_integer(userinfo.get("download")),
        total_bytes=_integer(userinfo.get("total")),
        expires_at=datetime.fromtimestamp(expires, UTC) if expires else None,
        announcement=_text(announcement),
        support_url=_text(headers.get("support-url")),
        web_url=_text(headers.get("profile-web-page-url")),
        update_interval=interval_hours * 3600 if interval_hours else None,
    )
