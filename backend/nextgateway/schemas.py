from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .system.network import NetworkConfig


class NodeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    protocol: Literal["vless", "hysteria2"]
    server: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    credentials: dict = Field(default_factory=dict)
    transport: dict = Field(default_factory=dict)
    tls: dict = Field(default_factory=dict)
    source: Literal["manual", "subscription"] = "manual"


class NodeRead(NodeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    fingerprint: str


class NodeSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    enabled: bool
    protocol: str
    server: str
    port: int
    source: str
    last_latency_ms: int | None = None
    last_probe_at: datetime | None = None
    last_probe_error: str | None = None


class NodeUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool


class NodeShare(BaseModel):
    uri: str


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    enabled: bool
    last_update: datetime | None
    last_success: datetime | None
    last_error: str | None
    update_interval: int
    nodes_count: int
    remote_name: str | None = None
    upload_bytes: int | None = None
    download_bytes: int | None = None
    total_bytes: int | None = None
    expires_at: datetime | None = None
    announcement: str | None = None
    support_url: str | None = None
    web_url: str | None = None


class SubscriptionDetail(SubscriptionRead):
    nodes: list[NodeSummary]


class SubscriptionShare(BaseModel):
    url: str


class SubscriptionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool
    update_interval: int = Field(ge=60, le=604800)


class SubscriptionDeviceProfile(BaseModel):
    user_agent: str = Field(min_length=1, max_length=255)
    hwid: str = Field(min_length=1, max_length=255)
    device_os: str = Field(min_length=1, max_length=100)
    os_version: str = Field(min_length=1, max_length=100)
    device_model: str = Field(min_length=1, max_length=255)
    app_version: str = Field(min_length=1, max_length=100)

    def request_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "X-HWID": self.hwid,
            "X-Device-OS": self.device_os,
            "X-Ver-OS": self.os_version,
            "X-Device-Model": self.device_model,
            "X-App-Version": self.app_version,
        }


class SubscriptionCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str = Field(min_length=10, max_length=8192)
    device_profile: SubscriptionDeviceProfile | None = None


class VlessImportRequest(BaseModel):
    uri: str = Field(min_length=10, max_length=8192)


class ProxyGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: Literal["select", "url-test", "fallback"] = "select"
    enabled: bool = True
    node_ids: list[str] = Field(default_factory=list)
    health_url: str | None = None
    interval: int | None = Field(default=None, ge=10)
    tolerance: int | None = Field(default=None, ge=0)


class ProxyGroupRead(ProxyGroupCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class RoutingRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    position: int = Field(ge=0)
    type: Literal[
        "DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6",
        "SRC-IP-CIDR", "DST-PORT", "SRC-PORT", "NETWORK", "RULE-SET", "GEOIP",
        "GEOSITE", "MATCH"
    ]
    value: str | None = None
    target: str = Field(min_length=1, max_length=255)
    comment: str | None = None

    @model_validator(mode="after")
    def validate_value(self):
        if self.type == "MATCH" and self.value not in (None, ""):
            raise ValueError("MATCH must not contain a value")
        if self.type != "MATCH" and not self.value:
            raise ValueError(f"{self.type} requires a value")
        return self


class RoutingRuleRead(RoutingRuleCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


class RoutingRuleOrder(BaseModel):
    rule_ids: list[str] = Field(min_length=1)


class CompilePreview(BaseModel):
    yaml: str


class MihomoConfigStatus(BaseModel):
    pending_changes: bool
    applied_available: bool
    error: str | None = None


class NetworkPreview(BaseModel):
    config: NetworkConfig
    netplan_yaml: str
    mutations_enabled: bool


class NetworkOperationRead(BaseModel):
    operation_id: str
    state: str


class MihomoHealthRead(BaseModel):
    installed: bool
    running: bool
    api_available: bool
    version: str | None
    error: str | None = None


class MihomoDashboardConnection(BaseModel):
    hostname: str
    port: int
    secret: str


class MihomoConfigApplyRequest(BaseModel):
    yaml: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    rollback_timeout: int = Field(default=120, ge=30, le=300)
