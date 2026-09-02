import urllib.parse
import urllib.request
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .db import get_session
from .models import (
    AuditEvent,
    InstallationState,
    Node,
    ProxyGroup,
    ProxyGroupGroupMember,
    RoutingRule,
    RuleProvider,
)
from .schemas import (
    CompilePreview,
    MihomoConfigApplyRequest,
    MihomoConfigStatus,
    MihomoDashboardConnection,
    MihomoHealthRead,
    NetworkOperationRead,
    NetworkPreview,
    RoutingPresetCreate,
    RoutingRuleRead,
    RoutingTemplateImport,
    RoutingTemplatePreview,
)
from .services.compiler import CompileError, CompileInput, dump_mihomo_yaml
from .services.mihomo_runtime import get_mihomo_health
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
