from datetime import datetime

from pydantic import BaseModel, Field

from ...system.gateway import GatewayConfig
from ...system.network import NetworkConfig


class EnvironmentRead(BaseModel):
    os: str
    interfaces: list[str]
    addresses: dict[str, list[str]]
    default_gateway: str | None
    default_interface: str | None


class SetupPlan(BaseModel):
    network: NetworkConfig
    gateway: GatewayConfig
    core: str = Field(default="mihomo", pattern="^mihomo$")
    core_version: str = Field(default="latest", min_length=1, max_length=32)
    install_zashboard: bool = True
    zashboard_version: str = Field(default="3.21.0", min_length=1, max_length=32)


class SetupSubscription(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=10, max_length=8192)


class InstallationRead(BaseModel):
    status: str
    current_step: str
    desired_config: dict
    last_error: str | None
    operation_kind: str | None
    operation_id: str | None
    completed_at: datetime | None
    environment: EnvironmentRead
