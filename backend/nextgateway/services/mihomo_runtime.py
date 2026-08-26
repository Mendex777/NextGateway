import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..settings import settings


@dataclass(frozen=True)
class MihomoHealth:
    installed: bool
    running: bool
    api_available: bool
    version: str | None
    error: str | None = None


def get_mihomo_health(api_url: str | None = None) -> MihomoHealth:
    binary_exists = settings.mihomo_binary_path.exists()
    if not settings.mihomo_secret_path.exists():
        return MihomoHealth(binary_exists, False, False, None, "API secret is missing")
    secret = settings.mihomo_secret_path.read_text().strip()
    request = urllib.request.Request(
        f"{api_url or settings.mihomo_api_url}/version",
        headers={"Authorization": f"Bearer {secret}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return MihomoHealth(binary_exists, False, False, None, str(exc))
    return MihomoHealth(binary_exists, True, True, payload.get("version"))
