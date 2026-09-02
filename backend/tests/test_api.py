from pathlib import Path

from fastapi.testclient import TestClient
from nextgateway.db import Base, get_session
from nextgateway.main import app
from nextgateway.settings import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def make_client(database: Path) -> TestClient:
    engine = create_engine(f"sqlite:///{database}", connect_args={"check_same_thread": False})
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def test_zashboard_route_is_registered_before_runtime_install() -> None:
    assert any(getattr(route, "name", None) == "zashboard" for route in app.routes)


def test_setup_can_be_reopened_without_blocking_manager(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "nextgateway.setup._environment",
        lambda: {
            "os": "Test OS",
            "interfaces": ["eth0"],
            "addresses": {"eth0": ["192.0.2.2/24"]},
            "default_gateway": "192.0.2.1",
            "default_interface": "eth0",
        },
    )
    with make_client(tmp_path / "reopen.db") as client:
        response = client.post("/api/v1/setup/reopen")
        assert response.status_code == 200
        assert response.json()["status"] == "setup_required"
        assert client.get("/api/v1/nodes").status_code == 200

    app.dependency_overrides.clear()


def test_import_build_group_rule_and_preview(tmp_path: Path) -> None:
    with make_client(tmp_path / "test.db") as client:
        imported = client.post(
            "/api/v1/nodes/import/vless",
            json={
                "uri": "vless://11111111-1111-4111-8111-111111111111@example.com:443"
                "?security=reality&type=xhttp&pbk=key&sid=abcd#DE-01"
            },
        )
        assert imported.status_code == 201
        node_id = imported.json()["id"]

        group = client.post(
            "/api/v1/proxy-groups",
            json={"name": "VPN", "type": "select", "node_ids": [node_id]},
        )
        assert group.status_code == 201

        rule = client.post(
            "/api/v1/routing-rules",
            json={"name": "Default", "position": 999, "type": "MATCH", "target": "VPN"},
        )
        assert rule.status_code == 201

        preview = client.post("/api/v1/config/mihomo/preview")
        assert preview.status_code == 200
        assert "MATCH,VPN" in preview.json()["yaml"]
        assert "external-controller: 192.168.1.84:9090" in preview.json()["yaml"]

    app.dependency_overrides.clear()


def test_manual_import_makes_duplicate_node_names_unique(tmp_path: Path) -> None:
    with make_client(tmp_path / "unique-names.db") as client:
        first = client.post(
            "/api/v1/nodes/import/vless",
            json={"uri": (
                "vless://11111111-1111-4111-8111-111111111111@example.com:443"
                "?type=tcp#Same"
            )},
        )
        second = client.post(
            "/api/v1/nodes/import/vless",
            json={"uri": (
                "vless://22222222-2222-4222-8222-222222222222@example.com:8443"
                "?type=tcp#Same"
            )},
        )
        assert first.json()["name"] == "Same"
        assert second.json()["name"] == "Same (2)"

    app.dependency_overrides.clear()


def test_delete_all_manual_nodes_keeps_subscription_nodes(tmp_path: Path) -> None:
    with make_client(tmp_path / "delete-manual.db") as client:
        manual = client.post(
            "/api/v1/nodes/import/vless",
            json={"uri": (
                "vless://11111111-1111-4111-8111-111111111111@example.com:443"
                "?type=tcp#Manual"
            )},
        )
        subscription_node = client.post(
            "/api/v1/nodes",
            json={
                "name": "Subscription node",
                "protocol": "vless",
                "server": "subscription.example.com",
                "port": 443,
                "credentials": {"uuid": "22222222-2222-4222-8222-222222222222"},
                "transport": {"type": "tcp"},
                "source": "subscription",
            },
        )
        assert manual.status_code == 201
        assert subscription_node.status_code == 201

        response = client.delete("/api/v1/nodes/manual/all")

        assert response.status_code == 200
        assert response.json() == {"deleted": 1}
        remaining = client.get("/api/v1/nodes").json()
        assert [node["name"] for node in remaining] == ["Subscription node"]

    app.dependency_overrides.clear()


def test_network_preview_does_not_apply(tmp_path: Path) -> None:
    with make_client(tmp_path / "preview.db") as client:
        response = client.post(
            "/api/v1/system/network/preview",
            json={
                "interface": "ens18",
                "address": "192.168.1.84/24",
                "gateway": "192.168.1.1",
                "dns": ["192.168.1.1"],
            },
        )
        assert response.status_code == 200
        assert response.json()["mutations_enabled"] is False
        assert "via: 192.168.1.1" in response.json()["netplan_yaml"]

        apply_response = client.post(
            "/api/v1/system/network/apply", json=response.json()["config"]
        )
        assert apply_response.status_code == 403

    app.dependency_overrides.clear()


def test_mihomo_status_detects_pending_changes(tmp_path: Path, monkeypatch) -> None:
    import importlib

    import yaml
    from nextgateway.system.mihomo_apply import normalized_config_digest

    applied = tmp_path / "mihomo.yaml"
    monkeypatch.setattr(
        importlib.import_module("nextgateway.modules.mihomo.router"),
        "current_mihomo_config_digest",
        lambda: normalized_config_digest(yaml.safe_load(applied.read_text())),
    )
    with make_client(tmp_path / "status.db") as client:
        node = client.post(
            "/api/v1/nodes/import/vless",
            json={
                "uri": "vless://11111111-1111-4111-8111-111111111111@example.com:443"
                "?security=reality&type=tcp&pbk=key&sid=abcd#Node"
            },
        ).json()
        client.post(
            "/api/v1/proxy-groups",
            json={"name": "VPN", "type": "select", "node_ids": [node["id"]]},
        )
        client.post(
            "/api/v1/routing-rules",
            json={"name": "Default", "position": 999, "type": "MATCH", "target": "VPN"},
        )
        preview = client.post("/api/v1/config/mihomo/preview").json()["yaml"]
        applied.write_text(preview + "secret: controller-secret\n")
        assert client.get("/api/v1/config/mihomo/status").json()["pending_changes"] is False

        client.put(
            f"/api/v1/nodes/{node['id']}",
            json={"name": "Renamed", "enabled": True},
        )
        assert client.get("/api/v1/config/mihomo/status").json()["pending_changes"] is True

    app.dependency_overrides.clear()


def test_mihomo_status_reports_incomplete_initial_config(tmp_path: Path) -> None:
    with make_client(tmp_path / "empty-status.db") as client:
        response = client.get("/api/v1/config/mihomo/status")

        assert response.status_code == 200
        assert response.json() == {
            "pending_changes": True,
            "applied_available": False,
            "error": "The last enabled routing rule must be MATCH",
        }

    app.dependency_overrides.clear()


def test_manager_subscription_create_does_not_reopen_setup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("nextgateway.setup._environment", lambda: {
        "os": "Test OS", "interfaces": ["eth0"],
        "addresses": {"eth0": ["192.0.2.2/24"]},
        "default_gateway": "192.0.2.1", "default_interface": "eth0",
    })
    monkeypatch.setattr(
        "nextgateway.services.subscription_manager.fetch_subscription_response",
            lambda _url, _headers=None: type("Response", (), {
            "content": (
                b"vless://11111111-1111-4111-8111-111111111111@example.com:443"
                b"?security=reality&type=tcp&pbk=key&sid=abcd#Node"
            ),
            "headers": {},
        })(),
    )
    secret_root = tmp_path / "subscriptions"
    monkeypatch.setattr(settings, "subscription_secret_root", secret_root)
    with make_client(tmp_path / "manager-subscription.db") as client:
        client.post("/api/v1/setup/reopen")
        before = client.get("/api/v1/setup/state").json()
        created = client.post(
            "/api/v1/subscriptions",
            json={"url": "https://example.com/subscription"},
        )
        assert created.status_code == 201
        assert created.json()["name"] == "Подписка"
        after = client.get("/api/v1/setup/state").json()
        assert after["status"] == before["status"]
        assert after["current_step"] == before["current_step"]

    app.dependency_overrides.clear()


def test_runtime_entities_can_be_updated_and_deleted(tmp_path: Path) -> None:
    with make_client(tmp_path / "manage.db") as client:
        node = client.post(
            "/api/v1/nodes/import/vless",
            json={
                "uri": "vless://11111111-1111-4111-8111-111111111111@example.com:443"
                "?security=reality&type=tcp&pbk=key&sid=abcd#Manual"
            },
        ).json()
        changed_node = client.put(
            f"/api/v1/nodes/{node['id']}", json={"name": "Renamed", "enabled": False}
        )
        assert changed_node.status_code == 200
        assert changed_node.json()["name"] == "Renamed"
        assert changed_node.json()["enabled"] is False
        group = client.post(
            "/api/v1/proxy-groups",
            json={"name": "Manual", "type": "select", "node_ids": []},
        ).json()
        updated = client.put(
            f"/api/v1/proxy-groups/{group['id']}",
            json={"name": "Manual", "type": "select", "node_ids": [node["id"]]},
        )
        assert updated.status_code == 200
        assert updated.json()["node_ids"] == [node["id"]]
        rule = client.post(
            "/api/v1/routing-rules",
            json={"name": "Manual", "position": 10, "type": "MATCH", "target": "Manual"},
        ).json()
        blocked = client.delete(f"/api/v1/proxy-groups/{group['id']}")
        assert blocked.status_code == 409
        changed_rule = client.put(
            f"/api/v1/routing-rules/{rule['id']}",
            json={"name": "Changed", "position": 20, "type": "MATCH", "target": "DIRECT"},
        )
        assert changed_rule.status_code == 200
        assert changed_rule.json()["target"] == "DIRECT"
        assert client.delete(f"/api/v1/routing-rules/{rule['id']}").status_code == 204
        assert client.delete(f"/api/v1/proxy-groups/{group['id']}").status_code == 204
        assert client.delete(f"/api/v1/nodes/{node['id']}").status_code == 204

    app.dependency_overrides.clear()
