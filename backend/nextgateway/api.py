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
