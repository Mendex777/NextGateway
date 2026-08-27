import pytest

from nextgateway.services import node_probe


def test_missing_runtime_proxy_uses_isolated_mihomo(monkeypatch, tmp_path):
    secret_path = tmp_path / "mihomo-api"
    secret_path.write_text("runtime-secret")
    proxy = {"name": "new node", "type": "vless"}

    monkeypatch.setattr(node_probe.settings, "mihomo_secret_path", secret_path)
    monkeypatch.setattr(
        node_probe,
        "_controller_delay",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            node_probe.NodeProbeError("Resource not found")
        ),
    )
    monkeypatch.setattr(node_probe, "_probe_isolated", lambda value, timeout: 123)

    assert node_probe.probe_node("new node", proxy=proxy) == 123


def test_runtime_probe_error_is_not_hidden_by_isolated_fallback(monkeypatch, tmp_path):
    secret_path = tmp_path / "mihomo-api"
    secret_path.write_text("runtime-secret")

    monkeypatch.setattr(node_probe.settings, "mihomo_secret_path", secret_path)
    monkeypatch.setattr(
        node_probe,
        "_controller_delay",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            node_probe.NodeProbeError("An error occurred in the delay test")
        ),
    )
    monkeypatch.setattr(
        node_probe,
        "_probe_isolated",
        lambda *_args, **_kwargs: pytest.fail("isolated probe must not be used"),
    )

    with pytest.raises(node_probe.NodeProbeError, match="delay test"):
        node_probe.probe_node("existing node", proxy={"name": "existing node"})
