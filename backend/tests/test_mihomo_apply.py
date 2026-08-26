import json
from pathlib import Path

import pytest
from nextgateway.system import mihomo_apply


def configure_paths(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "etc/mihomo/config.yaml"
    secret = tmp_path / "etc/nextgateway/secrets/mihomo-api"
    config.parent.mkdir(parents=True)
    secret.parent.mkdir(parents=True)
    config.write_text("tun:\n  enable: false\nrules:\n- MATCH,DIRECT\n")
    secret.write_text("private")
    monkeypatch.setattr(mihomo_apply, "CONFIG", config)
    monkeypatch.setattr(mihomo_apply, "SECRET", secret)
    monkeypatch.setattr(mihomo_apply, "STATE_ROOT", tmp_path / "state")


def test_prepare_injects_local_controller_and_secret(tmp_path: Path, monkeypatch) -> None:
    configure_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(mihomo_apply, "_run", lambda *_args, **_kwargs: None)
    operation_id = mihomo_apply.prepare_config(
        "external-controller: 0.0.0.0:9090\nsecret: exposed\nrules: [MATCH,DIRECT]\n"
    )
    candidate = (mihomo_apply.STATE_ROOT / operation_id / "config.candidate").read_text()
    assert "127.0.0.1:9090" in candidate
    assert "private" in candidate
    assert "exposed" not in candidate


def test_apply_failure_restores_config(tmp_path: Path, monkeypatch) -> None:
    configure_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(mihomo_apply, "_run", lambda *_args, **_kwargs: None)
    operation_id = mihomo_apply.prepare_config("tun:\n  enable: true\nrules: [MATCH,DIRECT]\n")

    def fail_api():
        raise OSError("API unavailable")

    monkeypatch.setattr(mihomo_apply, "_wait_for_api", fail_api)
    with pytest.raises(RuntimeError, match="rolled back"):
        mihomo_apply.apply_config(operation_id)
    assert "enable: false" in mihomo_apply.CONFIG.read_text()
    state = json.loads((mihomo_apply.STATE_ROOT / operation_id / "state.json").read_text())
    assert state["state"] == "rolled_back"
