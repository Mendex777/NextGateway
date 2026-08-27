import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .db import get_session
from .models import (
    AuditEvent,
    InstallationState,
    Node,
    ProxyGroup,
    ProxyGroupGroupMember,
    ProxyGroupMember,
    RoutingRule,
    RuleProvider,
    Subscription,
    SubscriptionNode,
)
from .schemas import (
    CompilePreview,
    MihomoConfigApplyRequest,
    MihomoConfigStatus,
    MihomoDashboardConnection,
    MihomoHealthRead,
    NetworkOperationRead,
    NetworkPreview,
    NodeCreate,
    NodeRead,
    NodeShare,
    NodeSummary,
    NodeUpdate,
    ProxyGroupCreate,
    ProxyGroupRead,
    RoutingPresetCreate,
    RoutingRuleCreate,
    RoutingRuleOrder,
    RoutingRuleRead,
    RoutingTemplateImport,
    RoutingTemplatePreview,
    RuleProviderCreate,
    RuleProviderRead,
    SubscriptionCreate,
    SubscriptionDetail,
    SubscriptionRead,
    SubscriptionShare,
    SubscriptionUpdate,
    VlessImportRequest,
)
from .services.compiler import CompileError, CompileInput, compile_node, dump_mihomo_yaml
from .services.hysteria2 import build_hysteria2_uri
from .services.mihomo_runtime import get_mihomo_health
from .services.node_probe import NodeProbeError, probe_node
from .services.subscription_fetch import SubscriptionFetchError
from .services.subscription_manager import refresh_subscription as refresh_subscription_data
from .services.subscription_source import read_subscription_source, write_subscription_source
from .services.subscriptions import SubscriptionParseError
from .services.vless import VlessParseError, build_vless_uri, node_fingerprint, parse_vless_uri
from .settings import settings
from .system.client import (
    HelperError,
    begin_mihomo_apply,
    begin_network_apply,
    confirm_mihomo_apply,
    confirm_network_apply,
    current_mihomo_config_digest,
    mihomo_apply_status,
    network_apply_status,
)
from .system.network import NetworkConfig, render_netplan, validate_operation_id

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]
_node_import_lock = Lock()


def _unique_node_name(session: Session, desired: str, exclude_id: str | None = None) -> str:
    names = set(
        session.scalars(
            select(Node.name).where(Node.id != exclude_id) if exclude_id else select(Node.name)
        )
    )
    if desired not in names:
        return desired
    suffix = 2
    while True:
        marker = f" ({suffix})"
        candidate = f"{desired[: 255 - len(marker)]}{marker}"
        if candidate not in names:
            return candidate
        suffix += 1


def _save_node(payload: NodeCreate, session: Session) -> Node:
    # Name selection and commit must be serialized. Without this lock, concurrent
    # imports can both observe the same free name and create an invalid Mihomo config.
    with _node_import_lock:
        values = payload.model_dump()
        values["name"] = _unique_node_name(session, payload.name)
        node = Node(**values, fingerprint=node_fingerprint(payload))
        session.add(node)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="This node already exists") from None
        session.refresh(node)
        return node


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scope": "manager-only"}


@router.get("/health/mihomo", response_model=MihomoHealthRead)
def mihomo_health(request: Request) -> MihomoHealthRead:
    api_url = f"http://{request.url.hostname or '127.0.0.1'}:9090"
    return MihomoHealthRead.model_validate(get_mihomo_health(api_url), from_attributes=True)


@router.get("/system/mihomo/dashboard", response_model=MihomoDashboardConnection)
def mihomo_dashboard_connection(request: Request) -> MihomoDashboardConnection:
    try:
        secret = settings.mihomo_secret_path.read_text().strip()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Mihomo API secret is unavailable") from exc
    return MihomoDashboardConnection(
        hostname=request.url.hostname or "127.0.0.1",
        port=9090,
        secret=secret,
    )


@router.post("/system/mihomo/config/apply", response_model=NetworkOperationRead)
def mihomo_config_apply(
    payload: MihomoConfigApplyRequest, session: SessionDep
) -> NetworkOperationRead:
    if not settings.system_mutations_enabled:
        raise HTTPException(status_code=403, detail="System mutations are disabled")
    try:
        operation_id = begin_mihomo_apply(payload.yaml, payload.rollback_timeout)
    except HelperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    session.add(
        AuditEvent(
            action="mihomo_config_apply",
            entity_type="mihomo_config",
            entity_id=operation_id,
            result="pending_confirmation",
        )
    )
    session.commit()
    return NetworkOperationRead(operation_id=operation_id, state="pending_confirmation")


@router.post("/system/mihomo/config/{operation_id}/confirm", response_model=NetworkOperationRead)
def mihomo_config_confirm(operation_id: str, session: SessionDep) -> NetworkOperationRead:
    try:
        operation_id = validate_operation_id(operation_id)
        confirm_mihomo_apply(operation_id)
    except (HelperError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    session.add(
        AuditEvent(
            action="mihomo_config_confirm",
            entity_type="mihomo_config",
            entity_id=operation_id,
            result="success",
        )
    )
    session.commit()
    return NetworkOperationRead(operation_id=operation_id, state="confirmed")


@router.get("/system/mihomo/config/{operation_id}", response_model=NetworkOperationRead)
def mihomo_config_status(operation_id: str) -> NetworkOperationRead:
    try:
        operation_id = validate_operation_id(operation_id)
        operation = mihomo_apply_status(operation_id)
    except (HelperError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return NetworkOperationRead(operation_id=operation_id, state=operation["state"])


@router.get("/nodes", response_model=list[NodeSummary])
def list_nodes(session: SessionDep) -> list[Node]:
    return list(session.scalars(select(Node).order_by(Node.name)))


@router.delete("/nodes/manual/all")
def delete_all_manual_nodes(session: SessionDep) -> dict[str, int]:
    node_ids = list(session.scalars(select(Node.id).where(Node.source == "manual")))
    if not node_ids:
        return {"deleted": 0}
    session.execute(delete(SubscriptionNode).where(SubscriptionNode.node_id.in_(node_ids)))
    session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.node_id.in_(node_ids)))
    session.execute(delete(Node).where(Node.id.in_(node_ids), Node.source == "manual"))
    session.commit()
    return {"deleted": len(node_ids)}


@router.get("/nodes/{node_id}/share", response_model=NodeShare)
def share_node(node_id: str, session: SessionDep) -> NodeShare:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        uri = build_vless_uri(node) if node.protocol == "vless" else build_hysteria2_uri(node)
        return NodeShare(uri=uri)
    except (VlessParseError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/subscriptions", response_model=list[SubscriptionRead])
def list_subscriptions(session: SessionDep) -> list[Subscription]:
    return list(session.scalars(select(Subscription).order_by(Subscription.name)))


@router.post("/subscriptions", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
def create_subscription(payload: SubscriptionCreate, session: SessionDep) -> Subscription:
    subscription_id = str(uuid.uuid4())
    secret_root = settings.subscription_secret_root
    secret_path = secret_root / f"{subscription_id}.url"
    try:
        secret_root.mkdir(parents=True, exist_ok=True)
        write_subscription_source(
            secret_path,
            payload.url,
            payload.device_profile.request_headers() if payload.device_profile else None,
        )
        subscription = Subscription(
            id=subscription_id,
            name=payload.name or subscription_id,
            secret_ref=str(secret_path),
        )
        session.add(subscription)
        session.commit()
        subscription = refresh_subscription_data(session, subscription)
        if payload.name is None:
            base_name = (subscription.remote_name or "Подписка").strip()[:255]
            candidate = base_name
            suffix = 2
            while session.scalar(
                select(Subscription.id).where(
                    Subscription.name == candidate,
                    Subscription.id != subscription.id,
                )
            ):
                marker = f" {suffix}"
                candidate = f"{base_name[: 255 - len(marker)]}{marker}"
                suffix += 1
            subscription.name = candidate
            session.commit()
            session.refresh(subscription)
        return subscription
    except IntegrityError as exc:
        session.rollback()
        stored = session.get(Subscription, subscription_id)
        if stored is not None:
            session.delete(stored)
            session.commit()
        secret_path.unlink(missing_ok=True)
        detail = (
            "Subscription name already exists"
            if "subscriptions.name" in str(exc)
            else "Subscription contains duplicate or conflicting entries"
        )
        raise HTTPException(status_code=409, detail=detail) from None
    except (OSError, SubscriptionFetchError, SubscriptionParseError) as exc:
        session.rollback()
        stored = session.get(Subscription, subscription_id)
        if stored is not None:
            session.delete(stored)
            session.commit()
        secret_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionDetail)
def get_subscription(subscription_id: str, session: SessionDep) -> SubscriptionDetail:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    nodes = list(
        session.scalars(
            select(Node)
            .join(SubscriptionNode, SubscriptionNode.node_id == Node.id)
            .where(SubscriptionNode.subscription_id == subscription_id)
            .order_by(SubscriptionNode.position)
        )
    )
    return SubscriptionDetail(
        **SubscriptionRead.model_validate(subscription).model_dump(), nodes=nodes
    )


@router.get("/subscriptions/{subscription_id}/share", response_model=SubscriptionShare)
def share_subscription(subscription_id: str, session: SessionDep) -> SubscriptionShare:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        return SubscriptionShare(url=read_subscription_source(Path(subscription.secret_ref)).url)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Subscription URL is unavailable") from exc


@router.put("/subscriptions/{subscription_id}", response_model=SubscriptionRead)
def update_subscription(
    subscription_id: str, payload: SubscriptionUpdate, session: SessionDep
) -> Subscription:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    subscription.name = payload.name
    subscription.enabled = payload.enabled
    subscription.update_interval = payload.update_interval
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Subscription name already exists") from None
    session.refresh(subscription)
    return subscription


@router.post("/subscriptions/{subscription_id}/refresh", response_model=SubscriptionRead)
def refresh_subscription(subscription_id: str, session: SessionDep) -> Subscription:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        return refresh_subscription_data(session, subscription)
    except (OSError, SubscriptionFetchError, SubscriptionParseError) as exc:
        subscription.last_error = str(exc)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/nodes/{node_id}/probe", response_model=NodeSummary)
def probe_single_node(node_id: str, request: Request, session: SessionDep) -> Node:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    node.last_probe_at = datetime.now(UTC)
    try:
        node.last_latency_ms = probe_node(
            node.name,
            api_url=f"http://{request.url.hostname or '127.0.0.1'}:9090",
            proxy=compile_node(node),
        )
        node.last_probe_error = None
    except (OSError, NodeProbeError) as exc:
        node.last_latency_ms = None
        node.last_probe_error = str(exc)[:1024]
    session.commit()
    session.refresh(node)
    return node


@router.post("/subscriptions/{subscription_id}/probe", response_model=list[NodeSummary])
def probe_subscription_nodes(
    subscription_id: str, request: Request, session: SessionDep
) -> list[Node]:
    if session.get(Subscription, subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    nodes = list(
        session.scalars(
            select(Node)
            .join(SubscriptionNode, SubscriptionNode.node_id == Node.id)
            .where(SubscriptionNode.subscription_id == subscription_id)
            .order_by(SubscriptionNode.position)
        )
    )
    for node in nodes:
        node.last_probe_at = datetime.now(UTC)
        try:
            node.last_latency_ms = probe_node(
                node.name,
                api_url=f"http://{request.url.hostname or '127.0.0.1'}:9090",
                proxy=compile_node(node),
            )
            node.last_probe_error = None
        except (OSError, NodeProbeError) as exc:
            node.last_latency_ms = None
            node.last_probe_error = str(exc)[:1024]
    session.commit()
    return nodes


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(subscription_id: str, session: SessionDep) -> None:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    node_ids = list(
        session.scalars(
            select(SubscriptionNode.node_id).where(
                SubscriptionNode.subscription_id == subscription_id
            )
        )
    )
    session.execute(
        delete(SubscriptionNode).where(SubscriptionNode.subscription_id == subscription_id)
    )
    for node_id in node_ids:
        remaining = session.scalar(
            select(func.count())
            .select_from(SubscriptionNode)
            .where(SubscriptionNode.node_id == node_id)
        )
        if not remaining:
            session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.node_id == node_id))
            session.execute(delete(Node).where(Node.id == node_id))
    secret_path = Path(subscription.secret_ref)
    session.delete(subscription)
    session.commit()
    try:
        secret_path.unlink(missing_ok=True)
    except OSError:
        pass


@router.post("/nodes", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
def create_node(payload: NodeCreate, session: SessionDep) -> Node:
    return _save_node(payload, session)


@router.put("/nodes/{node_id}", response_model=NodeSummary)
def update_node(node_id: str, payload: NodeUpdate, session: SessionDep) -> Node:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    node.name = _unique_node_name(session, payload.name, exclude_id=node.id)
    node.enabled = payload.enabled
    session.commit()
    session.refresh(node)
    return node


@router.delete("/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(node_id: str, session: SessionDep) -> None:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    session.execute(delete(SubscriptionNode).where(SubscriptionNode.node_id == node_id))
    session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.node_id == node_id))
    session.delete(node)
    session.commit()


@router.post("/nodes/import/vless/preview", response_model=NodeCreate)
def preview_vless(payload: VlessImportRequest) -> NodeCreate:
    try:
        return parse_vless_uri(payload.uri)
    except VlessParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/nodes/import/vless", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
def import_vless(payload: VlessImportRequest, session: SessionDep) -> Node:
    try:
        node = parse_vless_uri(payload.uri)
    except VlessParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _save_node(node, session)


def _group_read(group: ProxyGroup) -> ProxyGroupRead:
    return ProxyGroupRead(
        id=group.id,
        name=group.name,
        type=group.type,
        enabled=group.enabled,
        node_ids=[member.node_id for member in group.members],
        health_url=group.health_url,
        interval=group.interval,
        tolerance=group.tolerance,
        group_ids=[member.member_group_id for member in group.group_members],
        include_direct=group.include_direct,
        include_reject=group.include_reject,
    )


@router.get("/proxy-groups", response_model=list[ProxyGroupRead])
def list_proxy_groups(session: SessionDep) -> list[ProxyGroupRead]:
    query = (
        select(ProxyGroup)
        .options(
            selectinload(ProxyGroup.members),
            selectinload(ProxyGroup.group_members).selectinload(ProxyGroupGroupMember.member_group),
        )
        .order_by(ProxyGroup.name)
    )
    return [_group_read(group) for group in session.scalars(query)]


@router.post("/proxy-groups", response_model=ProxyGroupRead, status_code=status.HTTP_201_CREATED)
def create_proxy_group(payload: ProxyGroupCreate, session: SessionDep) -> ProxyGroupRead:
    existing_nodes = set(session.scalars(select(Node.id).where(Node.id.in_(payload.node_ids))))
    missing = set(payload.node_ids) - existing_nodes
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown node IDs: {sorted(missing)}")
    existing_groups = set(
        session.scalars(select(ProxyGroup.id).where(ProxyGroup.id.in_(payload.group_ids)))
    )
    if missing := set(payload.group_ids) - existing_groups:
        raise HTTPException(status_code=422, detail=f"Unknown group IDs: {sorted(missing)}")
    group = ProxyGroup(
        name=payload.name,
        type=payload.type,
        enabled=payload.enabled,
        health_url=payload.health_url,
        interval=payload.interval,
        tolerance=payload.tolerance,
        include_direct=payload.include_direct,
        include_reject=payload.include_reject,
    )
    group.members = [
        ProxyGroupMember(node_id=node_id, position=position)
        for position, node_id in enumerate(payload.node_ids)
    ]
    group.group_members = [
        ProxyGroupGroupMember(member_group_id=value, position=position)
        for position, value in enumerate(payload.group_ids)
    ]
    session.add(group)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Proxy group name already exists") from None
    session.expire(group, ["members"])
    return _group_read(group)


@router.put("/proxy-groups/{group_id}", response_model=ProxyGroupRead)
def update_proxy_group(
    group_id: str, payload: ProxyGroupCreate, session: SessionDep
) -> ProxyGroupRead:
    group = session.get(ProxyGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Proxy group not found")
    if group.id in payload.group_ids:
        raise HTTPException(status_code=422, detail="A group cannot include itself")
    existing_nodes = set(session.scalars(select(Node.id).where(Node.id.in_(payload.node_ids))))
    if missing := set(payload.node_ids) - existing_nodes:
        raise HTTPException(status_code=422, detail=f"Unknown node IDs: {sorted(missing)}")
    existing_groups = set(
        session.scalars(select(ProxyGroup.id).where(ProxyGroup.id.in_(payload.group_ids)))
    )
    if missing := set(payload.group_ids) - existing_groups:
        raise HTTPException(status_code=422, detail=f"Unknown group IDs: {sorted(missing)}")
    group.name = payload.name
    group.type = payload.type
    group.enabled = payload.enabled
    group.health_url = payload.health_url
    group.interval = payload.interval
    group.tolerance = payload.tolerance
    group.include_direct = payload.include_direct
    group.include_reject = payload.include_reject
    session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.group_id == group.id))
    session.add_all(
        ProxyGroupMember(group_id=group.id, node_id=node_id, position=position)
        for position, node_id in enumerate(payload.node_ids)
    )
    session.execute(delete(ProxyGroupGroupMember).where(ProxyGroupGroupMember.group_id == group.id))
    session.add_all(
        ProxyGroupGroupMember(group_id=group.id, member_group_id=value, position=position)
        for position, value in enumerate(payload.group_ids)
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Proxy group name already exists") from None
    session.expire(group, ["members"])
    return _group_read(group)


@router.delete("/proxy-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_proxy_group(group_id: str, session: SessionDep) -> None:
    group = session.get(ProxyGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Proxy group not found")
    references = session.scalar(
        select(func.count()).select_from(RoutingRule).where(RoutingRule.target == group.name)
    )
    if references:
        raise HTTPException(
            status_code=409,
            detail=f"Proxy group is used by {references} routing rule(s)",
        )
    session.delete(group)
    session.commit()


@router.get("/routing-rules", response_model=list[RoutingRuleRead])
def list_routing_rules(session: SessionDep) -> list[RoutingRule]:
    return list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))


@router.post("/routing-rules", response_model=RoutingRuleRead, status_code=status.HTTP_201_CREATED)
def create_routing_rule(payload: RoutingRuleCreate, session: SessionDep) -> RoutingRule:
    rule = RoutingRule(**payload.model_dump())
    session.add(rule)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Routing rule position already exists"
        ) from None
    session.refresh(rule)
    return rule


@router.put("/routing-rules/{rule_id}", response_model=RoutingRuleRead)
def update_routing_rule(
    rule_id: str, payload: RoutingRuleCreate, session: SessionDep
) -> RoutingRule:
    rule = session.get(RoutingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    for field, value in payload.model_dump().items():
        setattr(rule, field, value)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Routing rule position already exists"
        ) from None
    session.refresh(rule)
    return rule


@router.post("/routing-rules/reorder", response_model=list[RoutingRuleRead])
def reorder_routing_rules(payload: RoutingRuleOrder, session: SessionDep) -> list[RoutingRule]:
    rules = list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
    by_id = {rule.id: rule for rule in rules}
    if len(payload.rule_ids) != len(set(payload.rule_ids)) or set(payload.rule_ids) != set(by_id):
        raise HTTPException(status_code=422, detail="rule_ids must contain every rule exactly once")
    for offset, rule in enumerate(rules):
        rule.position = -(offset + 1)
    session.flush()
    for position, rule_id in enumerate(payload.rule_ids):
        by_id[rule_id].position = position * 10
    session.commit()
    return list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))


@router.delete("/routing-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routing_rule(rule_id: str, session: SessionDep) -> None:
    rule = session.get(RoutingRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    session.delete(rule)
    session.commit()


@router.get("/rule-providers", response_model=list[RuleProviderRead])
def list_rule_providers(session: SessionDep) -> list[RuleProvider]:
    return list(session.scalars(select(RuleProvider).order_by(RuleProvider.name)))


@router.post(
    "/rule-providers", response_model=RuleProviderRead, status_code=status.HTTP_201_CREATED
)
def create_rule_provider(payload: RuleProviderCreate, session: SessionDep) -> RuleProvider:
    provider = RuleProvider(**payload.model_dump())
    session.add(provider)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Rule provider name already exists") from None
    session.refresh(provider)
    return provider


@router.put("/rule-providers/{provider_id}", response_model=RuleProviderRead)
def update_rule_provider(
    provider_id: str, payload: RuleProviderCreate, session: SessionDep
) -> RuleProvider:
    provider = session.get(RuleProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Rule provider not found")
    for field, value in payload.model_dump().items():
        setattr(provider, field, value)
    session.commit()
    session.refresh(provider)
    return provider


@router.delete("/rule-providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule_provider(provider_id: str, session: SessionDep) -> None:
    provider = session.get(RuleProvider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Rule provider not found")
    session.delete(provider)
    session.commit()


SERVICE_PRESETS = (
    ("youtube", "📹 YouTube"),
    ("telegram", "📲 Telegram"),
    ("meta", "🌐 Meta / Instagram"),
    ("whatsapp", "💬 WhatsApp"),
    ("discord", "🎙️ Discord"),
    ("category-ai-!cn", "🤖 OpenAI и AI"),
    ("google", "🍀 Google"),
    ("github", "👨‍💻 GitHub"),
    ("steam", "🎮 Steam"),
    ("tiktok", "🎵 TikTok"),
    ("netflix", "🎥 Netflix"),
    ("apple", "🍏 Apple"),
    ("microsoft", "🪟 Microsoft"),
    ("onedrive", "🐬 OneDrive"),
)
SERVICE_IP_PRESETS = (
    ("telegram", "📲 Telegram", "geo/geoip"),
    ("google", "🍀 Google", "geo/geoip"),
    ("netflix", "🎥 Netflix", "geo/geoip"),
    ("apple", "🍏 Apple", "geo-lite/geoip"),
)


def _fetch_routing_template(url: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "raw.githubusercontent.com",
        "github.com",
    }:
        raise HTTPException(status_code=422, detail="Only HTTPS GitHub template URLs are allowed")
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            raw = response.read(1_048_577)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Template download failed: {exc}") from None
    if len(raw) > 1_048_576:
        raise HTTPException(status_code=422, detail="Template is too large")
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid template YAML: {exc}") from None
    if not isinstance(data, dict) or data.get("schema") != "nextgateway-routing-template/v1":
        raise HTTPException(status_code=422, detail="Unsupported routing template schema")
    if not isinstance(data.get("providers"), dict) or not isinstance(data.get("services"), list):
        raise HTTPException(status_code=422, detail="Template must contain providers and services")
    return data


@router.post("/routing-templates/preview", response_model=RoutingTemplatePreview)
def preview_routing_template(
    payload: RoutingTemplateImport, session: SessionDep
) -> RoutingTemplatePreview:
    if session.get(ProxyGroup, payload.base_group_id) is None:
        raise HTTPException(status_code=404, detail="Base proxy group not found")
    data = _fetch_routing_template(payload.url)
    services = data["services"]
    return RoutingTemplatePreview(
        name=str(data.get("name", data.get("id", "Template"))),
        version=str(data.get("version", "0")),
        providers=len(data["providers"]),
        groups=[str(item["name"]) for item in services],
        rules=sum(len(item.get("providers", [])) for item in services) + 1,
    )


@router.post("/routing-templates/import", response_model=list[RoutingRuleRead])
def import_routing_template(
    payload: RoutingTemplateImport, session: SessionDep
) -> list[RoutingRule]:
    data = _fetch_routing_template(payload.url)
    global SERVICE_PRESETS, SERVICE_IP_PRESETS
    old_services, old_ips = SERVICE_PRESETS, SERVICE_IP_PRESETS
    try:
        SERVICE_PRESETS = tuple((str(item["id"]), str(item["name"])) for item in data["services"])
        SERVICE_IP_PRESETS = ()
        install_service_routing_preset(
            RoutingPresetCreate(base_group_id=payload.base_group_id), session
        )
        providers = {item.name: item for item in session.scalars(select(RuleProvider))}
        for key, spec in data["providers"].items():
            name = f"service-{key}"
            provider = providers.get(name)
            if provider is None:
                provider = RuleProvider(name=name)
                session.add(provider)
            provider.type = "http"
            provider.behavior = str(spec["behavior"])
            provider.format = "mrs"
            provider.url = str(spec["url"])
            provider.path = f"./rules/{name}.mrs"
            provider.interval = int(spec.get("interval", 86400))
            provider.proxy = "DIRECT"
        session.flush()
        preset_rules = list(
            session.scalars(select(RoutingRule).where(RoutingRule.source == "service-preset"))
        )
        for rule in preset_rules:
            session.delete(rule)
        session.flush()
        existing = list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
        for i, rule in enumerate(existing):
            rule.position = -(i + 1)
        session.flush()
        ordered = [rule for rule in existing if rule.type != "MATCH"]
        for service in data["services"]:
            for key in service.get("providers", []):
                ordered.append(
                    RoutingRule(
                        name=str(service["name"]),
                        enabled=True,
                        position=0,
                        type="RULE-SET",
                        value=f"service-{key}",
                        target=str(service["name"]),
                        source="service-preset",
                    )
                )
        ordered.extend(
            [rule for rule in existing if rule.type == "MATCH"]
            or [
                RoutingRule(
                    name="Остальной трафик",
                    enabled=True,
                    position=0,
                    type="MATCH",
                    target=session.get(ProxyGroup, payload.base_group_id).name,
                    source="service-preset",
                )
            ]
        )
        for i, rule in enumerate(ordered):
            rule.position = i * 10
            session.add(rule)
        session.commit()
        return list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
    finally:
        SERVICE_PRESETS, SERVICE_IP_PRESETS = old_services, old_ips


@router.post("/routing-presets/services", response_model=list[RoutingRuleRead])
def install_service_routing_preset(
    payload: RoutingPresetCreate, session: SessionDep
) -> list[RoutingRule]:
    base = session.get(ProxyGroup, payload.base_group_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Base proxy group not found")
    groups_by_name = {item.name: item for item in session.scalars(select(ProxyGroup))}
    providers_by_name = {item.name: item for item in session.scalars(select(RuleProvider))}
    for slug, label in SERVICE_PRESETS:
        provider_name = f"service-{slug.replace('!', 'not-')}"
        if provider_name not in providers_by_name:
            session.add(
                RuleProvider(
                    name=provider_name,
                    type="http",
                    behavior="domain",
                    format="mrs",
                    url=f"https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/geo/geosite/{slug}.mrs",
                    path=f"./rules/{provider_name}.mrs",
                    interval=86400,
                    proxy="DIRECT",
                )
            )
        if label not in groups_by_name:
            group = ProxyGroup(name=label, type="select", enabled=True, include_direct=True)
            group.group_members = [ProxyGroupGroupMember(member_group_id=base.id, position=0)]
            session.add(group)
    for slug, _label, directory in SERVICE_IP_PRESETS:
        provider_name = f"service-{slug}-ip"
        if provider_name not in providers_by_name:
            session.add(
                RuleProvider(
                    name=provider_name,
                    type="http",
                    behavior="ipcidr",
                    format="mrs",
                    url=f"https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/meta/{directory}/{slug}.mrs",
                    path=f"./rules/{provider_name}.mrs",
                    interval=86400,
                    proxy="DIRECT",
                )
            )
    session.flush()
    existing = list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
    for index, rule in enumerate(existing):
        rule.position = -(index + 1)
    session.flush()
    manual = [rule for rule in existing if rule.source != "service-preset" and rule.type != "MATCH"]
    matches = [
        rule for rule in existing if rule.source != "service-preset" and rule.type == "MATCH"
    ]
    for rule in existing:
        if rule.source == "service-preset":
            session.delete(rule)
    session.flush()
    ordered = list(manual)
    for slug, label in SERVICE_PRESETS:
        provider_name = f"service-{slug.replace('!', 'not-')}"
        ordered.append(
            RoutingRule(
                name=label,
                enabled=True,
                position=0,
                type="RULE-SET",
                value=provider_name,
                target=label,
                source="service-preset",
            )
        )
    for slug, label, _directory in SERVICE_IP_PRESETS:
        ordered.append(
            RoutingRule(
                name=f"{label} · IP",
                enabled=True,
                position=0,
                type="RULE-SET",
                value=f"service-{slug}-ip",
                target=label,
                source="service-preset",
            )
        )
    ordered.extend(
        matches
        or [
            RoutingRule(
                name="Остальной трафик",
                enabled=True,
                position=0,
                type="MATCH",
                value=None,
                target=base.name,
                source="service-preset",
            )
        ]
    )
    for position, rule in enumerate(ordered):
        rule.position = position * 10
        session.add(rule)
    session.commit()
    return list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))


@router.post("/config/mihomo/preview", response_model=CompilePreview)
def compile_preview(session: SessionDep) -> CompilePreview:
    nodes = list(session.scalars(select(Node).order_by(Node.name)))
    groups_query = select(ProxyGroup).options(
        selectinload(ProxyGroup.members),
        selectinload(ProxyGroup.group_members).selectinload(ProxyGroupGroupMember.member_group),
    )
    groups = list(session.scalars(groups_query))
    rules = list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
    providers = list(session.scalars(select(RuleProvider).order_by(RuleProvider.name)))
    try:
        installation = session.get(InstallationState, 1)
        desired = installation.desired_config if installation else {}
        network = desired.get("network", {})
        gateway = desired.get("gateway", {})
        lan_address = str(network.get("address", "192.168.1.84/24")).split("/", 1)[0]
        output = dump_mihomo_yaml(
            CompileInput(
                nodes=nodes,
                groups=groups,
                rules=rules,
                rule_providers=providers,
                interface_name=network.get("interface", "ens18"),
                lan_address=lan_address,
                local_networks=(gateway.get("lan_subnet", "192.168.1.0/24"),),
                controller_address=lan_address,
            )
        )
    except (CompileError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return CompilePreview(yaml=output)


@router.get("/config/mihomo/status", response_model=MihomoConfigStatus)
def mihomo_config_change_status(session: SessionDep) -> MihomoConfigStatus:
    try:
        desired = compile_preview(session).yaml
    except HTTPException as exc:
        return MihomoConfigStatus(
            pending_changes=True,
            applied_available=False,
            error=str(exc.detail),
        )
    try:
        desired_document = yaml.safe_load(desired) or {}
        from .system.mihomo_apply import normalized_config_digest

        desired_digest = normalized_config_digest(desired_document)
        applied_digest = current_mihomo_config_digest()
        return MihomoConfigStatus(
            pending_changes=desired_digest != applied_digest,
            applied_available=True,
        )
    except (OSError, HelperError) as exc:
        return MihomoConfigStatus(
            pending_changes=True,
            applied_available=False,
            error=str(exc),
        )
    except yaml.YAMLError as exc:
        return MihomoConfigStatus(
            pending_changes=True,
            applied_available=True,
            error=f"Applied Mihomo configuration is invalid: {exc}",
        )


@router.post("/system/network/preview", response_model=NetworkPreview)
def network_preview(payload: NetworkConfig) -> NetworkPreview:
    return NetworkPreview(
        config=payload,
        netplan_yaml=render_netplan(payload),
        mutations_enabled=settings.system_mutations_enabled,
    )


@router.post("/system/network/apply", response_model=NetworkOperationRead)
def network_apply(payload: NetworkConfig, session: SessionDep) -> NetworkOperationRead:
    if not settings.system_mutations_enabled:
        raise HTTPException(status_code=403, detail="System mutations are disabled")
    try:
        operation_id = begin_network_apply(payload)
    except HelperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    session.add(
        AuditEvent(
            action="network_apply",
            entity_type="system_network",
            entity_id=operation_id,
            after=payload.model_dump(),
            result="pending_confirmation",
        )
    )
    session.commit()
    return NetworkOperationRead(operation_id=operation_id, state="pending_confirmation")


@router.post("/system/network/{operation_id}/confirm", response_model=NetworkOperationRead)
def network_confirm(operation_id: str, session: SessionDep) -> NetworkOperationRead:
    if not settings.system_mutations_enabled:
        raise HTTPException(status_code=403, detail="System mutations are disabled")
    try:
        operation_id = validate_operation_id(operation_id)
        confirm_network_apply(operation_id)
    except (HelperError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    session.add(
        AuditEvent(
            action="network_confirm",
            entity_type="system_network",
            entity_id=operation_id,
            result="success",
        )
    )
    session.commit()
    return NetworkOperationRead(operation_id=operation_id, state="confirmed")


@router.get("/system/network/{operation_id}", response_model=NetworkOperationRead)
def network_status(operation_id: str) -> NetworkOperationRead:
    if not settings.system_mutations_enabled:
        raise HTTPException(status_code=403, detail="System mutations are disabled")
    try:
        operation_id = validate_operation_id(operation_id)
        operation = network_apply_status(operation_id)
    except (HelperError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return NetworkOperationRead(operation_id=operation_id, state=operation["state"])
