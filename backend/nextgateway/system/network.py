import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

INTERFACE_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{1,32}$")


class NetworkConfig(BaseModel):
    interface: str
    address: str
    gateway: str
    dns: list[str] = Field(min_length=1, max_length=4)
    rollback_timeout: int = Field(default=90, ge=30, le=300)

    @field_validator("interface")
    @classmethod
    def validate_interface(cls, value: str) -> str:
        if not INTERFACE_PATTERN.fullmatch(value):
            raise ValueError("Invalid network interface name")
        return value

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: str) -> str:
        return str(ipaddress.IPv4Interface(value))

    @field_validator("gateway")
    @classmethod
    def validate_gateway(cls, value: str) -> str:
        return str(ipaddress.IPv4Address(value))

    @field_validator("dns")
    @classmethod
    def validate_dns(cls, values: list[str]) -> list[str]:
        return [str(ipaddress.ip_address(value)) for value in values]

    @model_validator(mode="after")
    def gateway_must_be_on_link(self):
        interface = ipaddress.IPv4Interface(self.address)
        gateway = ipaddress.IPv4Address(self.gateway)
        if gateway not in interface.network:
            raise ValueError("Gateway must be in the configured IPv4 subnet")
        if gateway == interface.ip:
            raise ValueError("Gateway and interface address must differ")
        return self


def render_netplan(config: NetworkConfig) -> str:
    document = {
        "network": {
            "version": 2,
            "renderer": "networkd",
            "ethernets": {
                config.interface: {
                    "dhcp4": False,
                    "addresses": [config.address],
                    "routes": [{"to": "default", "via": config.gateway}],
                    "nameservers": {"addresses": config.dns},
                }
            },
        }
    }
    return yaml.safe_dump(document, sort_keys=False)


@dataclass(frozen=True)
class NetworkPaths:
    managed_config: Path = Path("/etc/netplan/90-nextgateway.yaml")
    state_root: Path = Path("/var/lib/nextgateway-system/network-operations")


def validate_operation_id(operation_id: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
        raise ValueError("Invalid operation ID")
    return operation_id
