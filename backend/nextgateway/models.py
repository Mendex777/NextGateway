import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Node(Base, TimestampMixin):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    protocol: Mapped[str] = mapped_column(String(32))
    server: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    credentials: Mapped[dict] = mapped_column(JSON, default=dict)
    transport: Mapped[dict] = mapped_column(JSON, default=dict)
    tls: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_probe_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def transport_type(self) -> str:
        default = "udp" if self.protocol == "hysteria2" else "tcp"
        return str((self.transport or {}).get("type", default))

    @property
    def security(self) -> str:
        default = "tls" if self.protocol == "hysteria2" else "none"
        security = str((self.tls or {}).get("security", default))
        encryption = str((self.credentials or {}).get("encryption", "none")).lower()
        if security == "none" and encryption.startswith("mlkem"):
            return "ml-kem-768"
        return security


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    secret_ref: Mapped[str] = mapped_column(String(255), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_update: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    update_interval: Mapped[int] = mapped_column(Integer, default=3600)
    nodes_count: Mapped[int] = mapped_column(Integer, default=0)
    remote_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upload_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    download_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    announcement: Mapped[str | None] = mapped_column(Text, nullable=True)
    support_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    web_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)


class SubscriptionNode(Base):
    __tablename__ = "subscription_nodes"
    __table_args__ = (UniqueConstraint("subscription_id", "node_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    subscription_id: Mapped[str] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class ProxyGroup(Base, TimestampMixin):
    __tablename__ = "proxy_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    type: Mapped[str] = mapped_column(String(32), default="select")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    health_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tolerance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    include_direct: Mapped[bool] = mapped_column(Boolean, default=False)
    include_reject: Mapped[bool] = mapped_column(Boolean, default=False)
    members: Mapped[list["ProxyGroupMember"]] = relationship(
        cascade="all, delete-orphan", order_by="ProxyGroupMember.position"
    )
    group_members: Mapped[list["ProxyGroupGroupMember"]] = relationship(
        cascade="all, delete-orphan", foreign_keys="ProxyGroupGroupMember.group_id",
        order_by="ProxyGroupGroupMember.position"
    )


class ProxyGroupMember(Base):
    __tablename__ = "proxy_group_members"
    __table_args__ = (UniqueConstraint("group_id", "node_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    group_id: Mapped[str] = mapped_column(ForeignKey("proxy_groups.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)


class ProxyGroupGroupMember(Base):
    __tablename__ = "proxy_group_group_members"
    __table_args__ = (UniqueConstraint("group_id", "member_group_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    group_id: Mapped[str] = mapped_column(ForeignKey("proxy_groups.id", ondelete="CASCADE"))
    member_group_id: Mapped[str] = mapped_column(ForeignKey("proxy_groups.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    member_group: Mapped[ProxyGroup] = relationship(foreign_keys=[member_group_id])


class RuleProvider(Base, TimestampMixin):
    __tablename__ = "rule_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    type: Mapped[str] = mapped_column(String(16), default="http")
    behavior: Mapped[str] = mapped_column(String(16), default="domain")
    format: Mapped[str] = mapped_column(String(16), default="mrs")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval: Mapped[int] = mapped_column(Integer, default=86400)
    proxy: Mapped[str] = mapped_column(String(255), default="DIRECT")


class RoutingRule(Base, TimestampMixin):
    __tablename__ = "routing_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, unique=True)
    type: Mapped[str] = mapped_column(String(32))
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    target: Mapped[str] = mapped_column(String(255))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(255), default="system")
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[str] = mapped_column(String(32), default="success")


class LocalUser(Base, TimestampMixin):
    __tablename__ = "local_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("local_users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user: Mapped[LocalUser] = relationship()


class InstallationState(Base, TimestampMixin):
    __tablename__ = "installation_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    status: Mapped[str] = mapped_column(String(32), default="setup_required")
    current_step: Mapped[str] = mapped_column(String(64), default="welcome")
    desired_config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    operation_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    operation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
