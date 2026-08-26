import json
import urllib.error
import urllib.parse
import urllib.request

from ..settings import settings


class NodeProbeError(RuntimeError):
    pass


def probe_node(name: str, timeout_ms: int = 5000, api_url: str | None = None) -> int:
    secret = settings.mihomo_secret_path.read_text().strip()
    encoded = urllib.parse.quote(name, safe="")
    query = urllib.parse.urlencode(
        {"url": "https://www.gstatic.com/generate_204", "timeout": timeout_ms}
    )
    request = urllib.request.Request(
        f"{api_url or settings.mihomo_api_url}/proxies/{encoded}/delay?{query}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_ms / 1000 + 2) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = payload.get("message") or str(exc)
        except (ValueError, OSError):
            message = str(exc)
        raise NodeProbeError(message) from exc
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise NodeProbeError(str(exc)) from exc
    delay = payload.get("delay")
    if not isinstance(delay, int) or delay <= 0:
        raise NodeProbeError("Mihomo did not return a valid delay")
    return delay
