import io
import json
from pathlib import Path

from nextgateway.services.mihomo_runtime import get_mihomo_health


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_authenticated_mihomo_health(tmp_path: Path, monkeypatch) -> None:
    secret = tmp_path / "mihomo-api"
    secret.write_text("private-secret")
    monkeypatch.setattr("nextgateway.services.mihomo_runtime.settings.mihomo_secret_path", secret)

    def urlopen(request, timeout):
        assert request.get_header("Authorization") == "Bearer private-secret"
        assert timeout == 3
        return Response(json.dumps({"version": "1.19.30"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    health = get_mihomo_health()
    assert health.running is True
    assert health.api_available is True
    assert health.version == "1.19.30"
