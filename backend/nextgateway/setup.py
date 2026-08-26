import json
import platform
import subprocess
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .api import SessionDep
from .models import (
    InstallationState,
    Node,
    ProxyGroup,
    ProxyGroupMember,
    RoutingRule,
    Subscription,
    SubscriptionNode,
)
from .services.compiler import CompileInput, dump_mihomo_yaml
from .services.subscription_fetch import SubscriptionFetchError, fetch_subscription_response
from .services.subscription_metadata import parse_subscription_metadata
from .services.subscriptions import SubscriptionParseError, parse_subscription, sync_nodes
from .settings import settings
from .system.client import (
    HelperError,
    begin_gateway_apply,
    begin_mihomo_apply,
    begin_network_apply,
    confirm_gateway_apply,
    confirm_mihomo_apply,
    confirm_network_apply,
    install_mihomo,
    install_zashboard,
)
from .system.gateway import GatewayConfig
from .system.network import NetworkConfig

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


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


def _ip_state() -> tuple[list[str], dict[str, list[str]], str | None, str | None]:
    try:
        links = json.loads(
            subprocess.run(
                ["/usr/sbin/ip", "-j", "address", "show"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        )
        routes = json.loads(
            subprocess.run(
                ["/usr/sbin/ip", "-j", "route", "show", "default"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Unable to inspect network state") from exc
    ignored_interfaces = {"lo", "mihomo"}
    interfaces = [link["ifname"] for link in links if link["ifname"] not in ignored_interfaces]
    addresses = {
        link["ifname"]: [
            f"{item['local']}/{item['prefixlen']}"
            for item in link.get("addr_info", [])
            if item.get("family") == "inet"
        ]
        for link in links
        if link["ifname"] not in ignored_interfaces
    }
    default = routes[0] if routes else {}
    return interfaces, addresses, default.get("gateway"), default.get("dev")


def _environment() -> EnvironmentRead:
    interfaces, addresses, gateway, interface = _ip_state()
    return EnvironmentRead(
        os=platform.freedesktop_os_release().get("PRETTY_NAME", platform.platform()),
        interfaces=interfaces,
        addresses=addresses,
        default_gateway=gateway,
        default_interface=interface,
    )


def _state(session: Session) -> InstallationState:
    current = session.get(InstallationState, 1)
    if current is None:
        current = InstallationState(id=1)
        session.add(current)
        session.commit()
        session.refresh(current)
    return current


def _reconcile(current: InstallationState, session: Session) -> InstallationState:
    changed = False
    if current.status == "applying" and current.current_step == "install_core":
        if settings.mihomo_binary_path.exists():
            current.status = "core_ready"
            current.current_step = "network"
            current.last_error = None
            changed = True
    if current.status == "applying" and current.current_step == "zashboard":
        if (settings.zashboard_dist / "index.html").is_file():
            current.status = "complete"
            current.current_step = "complete"
            current.last_error = None
            current.completed_at = datetime.now().astimezone()
            changed = True
    if changed:
        session.commit()
        session.refresh(current)
    return current


def _read(current: InstallationState) -> InstallationRead:
    return InstallationRead(
        status=current.status,
        current_step=current.current_step,
        desired_config=current.desired_config,
        last_error=current.last_error,
        operation_kind=current.operation_kind,
        operation_id=current.operation_id,
        completed_at=current.completed_at,
        environment=_environment(),
    )


@router.get("/state", response_model=InstallationRead)
def installation_state(session: SessionDep) -> InstallationRead:
    return _read(_reconcile(_state(session), session))


@router.post("/reopen", response_model=InstallationRead)
def reopen_installation(session: SessionDep) -> InstallationRead:
    current = _state(session)
    if current.operation_id:
        raise HTTPException(status_code=409, detail="Confirm or roll back the pending change first")
    current.status = "setup_required"
    current.current_step = "welcome"
    current.last_error = None
    current.completed_at = None
    session.commit()
    session.refresh(current)
    return _read(current)


@router.put("/plan", response_model=InstallationRead)
def save_plan(payload: SetupPlan, session: SessionDep) -> InstallationRead:
    current = _state(session)
    if current.status == "complete":
        raise HTTPException(status_code=409, detail="Installation is already complete")
    current.desired_config = payload.model_dump(mode="json")
    current.status = "plan_ready"
    current.current_step = "review"
    current.last_error = None
    session.commit()
    session.refresh(current)
    return _read(current)


def _failed(current: InstallationState, session: Session, exc: Exception) -> None:
    current.status = "failed"
    current.last_error = str(exc)
    session.commit()


@router.post("/core/install", response_model=InstallationRead)
def setup_install_core(session: SessionDep) -> InstallationRead:
    current = _state(session)
    retrying = current.status == "failed" and current.current_step == "install_core"
    if current.status != "plan_ready" and not retrying:
        raise HTTPException(status_code=409, detail="A setup plan is required")
    version = SetupPlan.model_validate(current.desired_config).core_version
    if version == "latest":
        raise HTTPException(status_code=422, detail="An explicit Mihomo version is required")
    current.status = "applying"
    current.current_step = "install_core"
    current.last_error = None
    session.commit()
    try:
        install_mihomo(version)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "core_ready"
    current.current_step = "network"
    session.commit()
    session.refresh(current)
    return _read(current)


@router.post("/network/apply", response_model=InstallationRead)
def setup_apply_network(session: SessionDep) -> InstallationRead:
    current = _state(session)
    retrying = current.status == "failed" and current.current_step == "network"
    if current.status != "core_ready" and not retrying:
        raise HTTPException(status_code=409, detail="The proxy core must be installed first")
    plan = SetupPlan.model_validate(current.desired_config)
    current.status = "applying"
    current.current_step = "network"
    current.last_error = None
    session.commit()
    try:
        operation_id = begin_network_apply(plan.network)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "network_pending_confirmation"
    current.operation_kind = "network"
    current.operation_id = operation_id
    session.commit()
    session.refresh(current)
    return _read(current)


@router.post("/network/confirm", response_model=InstallationRead)
def setup_confirm_network(session: SessionDep) -> InstallationRead:
    current = _state(session)
    if current.status != "network_pending_confirmation" or not current.operation_id:
        raise HTTPException(status_code=409, detail="No network change is awaiting confirmation")
    try:
        confirm_network_apply(current.operation_id)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "network_ready"
    current.current_step = "gateway"
    current.operation_kind = None
    current.operation_id = None
    session.commit()
    session.refresh(current)
    return _read(current)


@router.post("/gateway/apply", response_model=InstallationRead)
def setup_apply_gateway(session: SessionDep) -> InstallationRead:
    current = _state(session)
    retrying = current.status == "failed" and current.current_step == "gateway"
    if current.status != "network_ready" and not retrying:
        raise HTTPException(status_code=409, detail="Network configuration must be confirmed first")
    plan = SetupPlan.model_validate(current.desired_config)
    current.status = "applying"
    current.current_step = "gateway"
    current.last_error = None
    session.commit()
    try:
        operation_id = begin_gateway_apply(plan.gateway)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "gateway_pending_confirmation"
    current.operation_kind = "gateway"
    current.operation_id = operation_id
    session.commit()
    session.refresh(current)
    return _read(current)


@router.post("/gateway/confirm", response_model=InstallationRead)
def setup_confirm_gateway(session: SessionDep) -> InstallationRead:
    current = _state(session)
    if current.status != "gateway_pending_confirmation" or not current.operation_id:
        raise HTTPException(status_code=409, detail="No gateway change is awaiting confirmation")
    try:
        confirm_gateway_apply(current.operation_id)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "gateway_ready"
    current.current_step = "subscription"
    current.operation_kind = None
    current.operation_id = None
    session.commit()
    session.refresh(current)
    return _read(current)


def _configure_default_profile(session: Session, source_ref: str | None = None) -> None:
    query = select(Node).where(Node.enabled.is_(True))
    if source_ref:
        query = (
            query.join(SubscriptionNode, SubscriptionNode.node_id == Node.id)
            .where(SubscriptionNode.subscription_id == source_ref)
            .order_by(SubscriptionNode.position)
        )
    else:
        query = query.order_by(Node.name)
    nodes = list(session.scalars(query))
    if not nodes:
        raise SubscriptionParseError("Subscription contains no supported nodes")
    group = session.scalar(select(ProxyGroup).where(ProxyGroup.name == "VPN-Auto"))
    if group is None:
        group = ProxyGroup(
            name="VPN-Auto",
            type="url-test",
            health_url="https://www.gstatic.com/generate_204",
            interval=300,
            tolerance=100,
        )
        session.add(group)
        session.flush()
    session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.group_id == group.id))
    session.add_all(
        ProxyGroupMember(group_id=group.id, node_id=node.id, position=position)
        for position, node in enumerate(nodes)
    )
    rule = session.scalar(select(RoutingRule).where(RoutingRule.position == 999))
    if rule is None:
        session.add(
            RoutingRule(
                name="Default via VPN",
                position=999,
                type="MATCH",
                target="VPN-Auto",
            )
        )
    else:
        rule.name = "Default via VPN"
        rule.type = "MATCH"
        rule.value = None
        rule.target = "VPN-Auto"
        rule.enabled = True
    session.commit()


@router.post("/subscription/import", response_model=InstallationRead)
def setup_import_subscription(payload: SetupSubscription, session: SessionDep) -> InstallationRead:
    current = _state(session)
    try:
        response = fetch_subscription_response(payload.url)
        parsed = parse_subscription(response.content)
        metadata = parse_subscription_metadata(response.headers)
    except (SubscriptionFetchError, SubscriptionParseError) as exc:
        current.last_error = str(exc)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    subscription = session.scalar(select(Subscription).where(Subscription.name == payload.name))
    source_ref = subscription.id if subscription else str(uuid.uuid4())
    secret_root = settings.subscription_secret_root
    secret_root.mkdir(parents=True, exist_ok=True)
    secret_path = secret_root / f"{source_ref}.url"
    secret_path.write_text(payload.url)
    secret_path.chmod(0o600)
    now = datetime.now().astimezone()
    if subscription is None:
        subscription = Subscription(
            id=source_ref,
            name=payload.name,
            secret_ref=str(secret_path),
        )
        session.add(subscription)
    subscription.last_update = now
    subscription.last_success = now
    subscription.last_error = None
    subscription.nodes_count = len(parsed.nodes)
    for field in (
        "remote_name", "upload_bytes", "download_bytes", "total_bytes", "expires_at",
        "announcement", "support_url", "web_url",
    ):
        setattr(subscription, field, getattr(metadata, field))
    if metadata.update_interval:
        subscription.update_interval = metadata.update_interval
    sync_nodes(session, parsed, source_ref)
    _configure_default_profile(session, source_ref)
    if current.status != "complete":
        current.status = "subscription_ready"
        current.current_step = "tun"
    current.last_error = None
    session.commit()
    session.refresh(current)
    return _read(current)


def _compiled_setup_config(current: InstallationState, session: Session) -> str:
    plan = SetupPlan.model_validate(current.desired_config)
    address = plan.network.address.split("/", maxsplit=1)[0]
    nodes = list(session.scalars(select(Node).order_by(Node.name)))
    groups = list(
        session.scalars(select(ProxyGroup).options(selectinload(ProxyGroup.members)))
    )
    rules = list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
    return dump_mihomo_yaml(
        CompileInput(
            nodes=nodes,
            groups=groups,
            rules=rules,
            interface_name=plan.network.interface,
            lan_address=address,
            local_networks=(plan.gateway.lan_subnet,),
            controller_address=address,
        )
    )


@router.post("/tun/apply", response_model=InstallationRead)
def setup_apply_tun(session: SessionDep) -> InstallationRead:
    current = _state(session)
    retrying = current.status == "failed" and current.current_step == "tun"
    if current.status != "subscription_ready" and not retrying:
        raise HTTPException(status_code=409, detail="A subscription must be imported first")
    config = _compiled_setup_config(current, session)
    current.status = "applying"
    current.current_step = "tun"
    current.last_error = None
    session.commit()
    try:
        operation_id = begin_mihomo_apply(config, 120)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "tun_pending_confirmation"
    current.operation_kind = "mihomo"
    current.operation_id = operation_id
    session.commit()
    session.refresh(current)
    return _read(current)


@router.post("/tun/confirm", response_model=InstallationRead)
def setup_confirm_tun(session: SessionDep) -> InstallationRead:
    current = _state(session)
    if current.status != "tun_pending_confirmation" or not current.operation_id:
        raise HTTPException(status_code=409, detail="No TUN change is awaiting confirmation")
    try:
        confirm_mihomo_apply(current.operation_id)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    plan = SetupPlan.model_validate(current.desired_config)
    current.status = "tun_ready" if plan.install_zashboard else "complete"
    current.current_step = "zashboard" if plan.install_zashboard else "complete"
    current.operation_kind = None
    current.operation_id = None
    current.completed_at = None if plan.install_zashboard else datetime.now().astimezone()
    session.commit()
    session.refresh(current)
    return _read(current)


@router.post("/zashboard/install", response_model=InstallationRead)
def setup_install_zashboard(session: SessionDep) -> InstallationRead:
    current = _state(session)
    retrying = current.status == "failed" and current.current_step == "zashboard"
    if current.status != "tun_ready" and not retrying:
        raise HTTPException(status_code=409, detail="TUN configuration must be confirmed first")
    plan = SetupPlan.model_validate(current.desired_config)
    if not plan.install_zashboard:
        raise HTTPException(status_code=409, detail="Zashboard is disabled in the setup plan")
    current.status = "applying"
    current.current_step = "zashboard"
    current.last_error = None
    session.commit()
    try:
        install_zashboard(plan.zashboard_version)
    except HelperError as exc:
        _failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "complete"
    current.current_step = "complete"
    current.completed_at = datetime.now().astimezone()
    session.commit()
    session.refresh(current)
    return _read(current)
