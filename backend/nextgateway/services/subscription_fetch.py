import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

MAX_SUBSCRIPTION_SIZE = 4 * 1024 * 1024


class SubscriptionFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class SubscriptionResponse:
    content: bytes
    headers: dict[str, str]


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SubscriptionFetchError("Subscription URL must be an HTTPS URL without userinfo")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SubscriptionFetchError("Subscription hostname cannot be resolved") from exc
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global:
            raise SubscriptionFetchError("Subscription URL resolves to a non-public address")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_subscription_response(
    url: str, request_headers: dict[str, str] | None = None
) -> SubscriptionResponse:
    _validate_url(url)
    opener = urllib.request.build_opener(SafeRedirectHandler())
    headers = {"User-Agent": "NextGateway/0.1"}
    headers.update(request_headers or {})
    request = urllib.request.Request(url, headers=headers)
    last_error: Exception | None = None
    for _attempt in range(3):
        try:
            with opener.open(request, timeout=90) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_SUBSCRIPTION_SIZE:
                    raise SubscriptionFetchError("Subscription response is too large")
                content = response.read(MAX_SUBSCRIPTION_SIZE + 1)
                headers = {key.lower(): value for key, value in response.headers.items()}
            break
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(512).decode("utf-8", errors="replace").strip()
            except OSError:
                detail = ""
            message = f"Subscription provider returned HTTP {exc.code}"
            if detail and "<html" not in detail.lower():
                message += f": {detail[:300]}"
            raise SubscriptionFetchError(message) from None
        except (OSError, urllib.error.URLError, ValueError) as exc:
            last_error = exc
    else:
        reason = str(last_error or "network error").strip()
        raise SubscriptionFetchError(
            f"Unable to download subscription after 3 attempts: {reason}"
        ) from None
    if len(content) > MAX_SUBSCRIPTION_SIZE:
        raise SubscriptionFetchError("Subscription response is too large")
    return SubscriptionResponse(content=content, headers=headers)


def fetch_subscription(url: str) -> bytes:
    return fetch_subscription_response(url).content
