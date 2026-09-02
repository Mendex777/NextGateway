import base64
from pathlib import Path

from fastapi.testclient import TestClient
from nextgateway.db import Base, get_session
from nextgateway.main import app
from nextgateway.modules.installation.schemas import EnvironmentRead
from nextgateway.services.subscription_fetch import SubscriptionResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_setup_state_and_validated_plan(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'setup.db'}", connect_args={"check_same_thread": False}
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_session():
        with testing_session() as session:
            yield session

    environment = EnvironmentRead(
        os="Ubuntu 24.04 LTS",
        interfaces=["ens18"],
        addresses={"ens18": ["192.168.1.84/24"]},
        default_gateway="192.168.1.1",
        default_interface="ens18",
    )
    monkeypatch.setattr("nextgateway.modules.installation.state.environment", lambda: environment)
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.settings.subscription_secret_root",
        tmp_path / "subscriptions",
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.install_mihomo",
        lambda version: {"version": version},
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.begin_network_apply", lambda config: "a" * 32
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.confirm_network_apply",
        lambda operation_id: None,
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.begin_gateway_apply", lambda config: "b" * 32
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.confirm_gateway_apply",
        lambda operation_id: None,
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.fetch_subscription_response",
        lambda url: SubscriptionResponse(
            content=base64.b64encode(
                b"vless://11111111-1111-4111-8111-111111111111@example.com:443"
                b"?security=tls&type=ws#Setup-Node"
            ),
            headers={"profile-title": "Test VPN"},
        ),
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.begin_mihomo_apply",
        lambda config, timeout: "c" * 32,
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.confirm_mihomo_apply",
        lambda operation_id: None,
    )
    monkeypatch.setattr(
        "nextgateway.modules.installation.router.install_zashboard",
        lambda version: {"version": version},
    )
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        initial = client.get("/api/v1/setup/state")
        assert initial.status_code == 200
        assert initial.json()["status"] == "setup_required"

        plan = client.put(
            "/api/v1/setup/plan",
            json={
                "network": {
                    "interface": "ens18",
                    "address": "192.168.1.84/24",
                    "gateway": "192.168.1.1",
                    "dns": ["192.168.1.1"],
                },
                "gateway": {"interface": "ens18", "lan_subnet": "192.168.1.0/24"},
                "core": "mihomo",
                "core_version": "1.19.30",
            },
        )
        assert plan.status_code == 200
        assert plan.json()["status"] == "plan_ready"
        assert plan.json()["desired_config"]["network"]["gateway"] == "192.168.1.1"

        invalid = client.put(
            "/api/v1/setup/plan",
            json={
                "network": {
                    "interface": "ens18; reboot",
                    "address": "192.168.1.84/24",
                    "gateway": "192.168.1.1",
                    "dns": ["192.168.1.1"],
                },
                "gateway": {"interface": "ens18", "lan_subnet": "192.168.1.0/24"},
            },
        )
        assert invalid.status_code == 422

        core = client.post("/api/v1/setup/core/install")
        assert core.status_code == 200
        assert core.json()["status"] == "core_ready"

        network = client.post("/api/v1/setup/network/apply")
        assert network.status_code == 200
        assert network.json()["operation_kind"] == "network"
        assert network.json()["operation_id"] == "a" * 32

        confirmed_network = client.post("/api/v1/setup/network/confirm")
        assert confirmed_network.status_code == 200
        assert confirmed_network.json()["status"] == "network_ready"

        gateway = client.post("/api/v1/setup/gateway/apply")
        assert gateway.status_code == 200
        assert gateway.json()["operation_kind"] == "gateway"

        confirmed_gateway = client.post("/api/v1/setup/gateway/confirm")
        assert confirmed_gateway.status_code == 200
        assert confirmed_gateway.json()["status"] == "gateway_ready"
        assert confirmed_gateway.json()["current_step"] == "subscription"

        subscription = client.post(
            "/api/v1/setup/subscription/import",
            json={"name": "Primary", "url": "https://subscriptions.example/user"},
        )
        assert subscription.status_code == 200
        assert subscription.json()["status"] == "subscription_ready"

        tun = client.post("/api/v1/setup/tun/apply")
        assert tun.status_code == 200
        assert tun.json()["operation_id"] == "c" * 32

        confirmed_tun = client.post("/api/v1/setup/tun/confirm")
        assert confirmed_tun.status_code == 200
        assert confirmed_tun.json()["status"] == "tun_ready"
        assert confirmed_tun.json()["current_step"] == "zashboard"

        zashboard = client.post("/api/v1/setup/zashboard/install")
        assert zashboard.status_code == 200
        assert zashboard.json()["status"] == "complete"
    app.dependency_overrides.clear()
