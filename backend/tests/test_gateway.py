import pytest
from nextgateway.system.gateway import GatewayConfig, render_nftables, render_sysctl, render_unit


def test_render_single_arm_gateway() -> None:
    config = GatewayConfig(interface="ens18", lan_subnet="192.168.1.0/24")
    nftables = render_nftables(config)
    assert "ip saddr 192.168.1.0/24" in nftables
    assert 'oifname "ens18" masquerade' in nftables
    assert "net.ipv4.ip_forward = 1" in render_sysctl()
    assert "Before=mihomo.service" in render_unit()


def test_reject_public_lan_subnet() -> None:
    with pytest.raises(ValueError, match="private"):
        GatewayConfig(interface="ens18", lan_subnet="8.8.8.0/24")
