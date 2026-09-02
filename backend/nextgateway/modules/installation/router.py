import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from ...api import SessionDep
from ...models import (
    Subscription,
)
from ...services.subscription_fetch import SubscriptionFetchError, fetch_subscription_response
from ...services.subscription_metadata import parse_subscription_metadata
from ...services.subscriptions import SubscriptionParseError, parse_subscription, sync_nodes
from ...settings import settings
from ...system.client import (
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
from .profile import compile_setup_config, configure_default_profile
from .schemas import InstallationRead, SetupPlan, SetupSubscription
from .state import get_state, mark_failed, read_state, reconcile

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/state", response_model=InstallationRead)
def installation_state(session: SessionDep) -> InstallationRead:
    return read_state(reconcile(get_state(session), session))


@router.post("/reopen", response_model=InstallationRead)
def reopen_installation(session: SessionDep) -> InstallationRead:
    current = get_state(session)
    if current.operation_id:
        raise HTTPException(status_code=409, detail="Confirm or roll back the pending change first")
    current.status = "setup_required"
    current.current_step = "welcome"
    current.last_error = None
    current.completed_at = None
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.put("/plan", response_model=InstallationRead)
def save_plan(payload: SetupPlan, session: SessionDep) -> InstallationRead:
    current = get_state(session)
    if current.status == "complete":
        raise HTTPException(status_code=409, detail="Installation is already complete")
    current.desired_config = payload.model_dump(mode="json")
    current.status = "plan_ready"
    current.current_step = "review"
    current.last_error = None
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/core/install", response_model=InstallationRead)
def setup_install_core(session: SessionDep) -> InstallationRead:
    current = get_state(session)
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
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "core_ready"
    current.current_step = "network"
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/network/apply", response_model=InstallationRead)
def setup_apply_network(session: SessionDep) -> InstallationRead:
    current = get_state(session)
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
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "network_pending_confirmation"
    current.operation_kind = "network"
    current.operation_id = operation_id
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/network/confirm", response_model=InstallationRead)
def setup_confirm_network(session: SessionDep) -> InstallationRead:
    current = get_state(session)
    if current.status != "network_pending_confirmation" or not current.operation_id:
        raise HTTPException(status_code=409, detail="No network change is awaiting confirmation")
    try:
        confirm_network_apply(current.operation_id)
    except HelperError as exc:
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "network_ready"
    current.current_step = "gateway"
    current.operation_kind = None
    current.operation_id = None
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/gateway/apply", response_model=InstallationRead)
def setup_apply_gateway(session: SessionDep) -> InstallationRead:
    current = get_state(session)
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
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "gateway_pending_confirmation"
    current.operation_kind = "gateway"
    current.operation_id = operation_id
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/gateway/confirm", response_model=InstallationRead)
def setup_confirm_gateway(session: SessionDep) -> InstallationRead:
    current = get_state(session)
    if current.status != "gateway_pending_confirmation" or not current.operation_id:
        raise HTTPException(status_code=409, detail="No gateway change is awaiting confirmation")
    try:
        confirm_gateway_apply(current.operation_id)
    except HelperError as exc:
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "gateway_ready"
    current.current_step = "subscription"
    current.operation_kind = None
    current.operation_id = None
    session.commit()
    session.refresh(current)
    return read_state(current)




@router.post("/subscription/import", response_model=InstallationRead)
def setup_import_subscription(payload: SetupSubscription, session: SessionDep) -> InstallationRead:
    current = get_state(session)
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
    configure_default_profile(session, source_ref)
    if current.status != "complete":
        current.status = "subscription_ready"
        current.current_step = "tun"
    current.last_error = None
    session.commit()
    session.refresh(current)
    return read_state(current)




@router.post("/tun/apply", response_model=InstallationRead)
def setup_apply_tun(session: SessionDep) -> InstallationRead:
    current = get_state(session)
    retrying = current.status == "failed" and current.current_step == "tun"
    if current.status != "subscription_ready" and not retrying:
        raise HTTPException(status_code=409, detail="A subscription must be imported first")
    config = compile_setup_config(current, session)
    current.status = "applying"
    current.current_step = "tun"
    current.last_error = None
    session.commit()
    try:
        operation_id = begin_mihomo_apply(config, 120)
    except HelperError as exc:
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "tun_pending_confirmation"
    current.operation_kind = "mihomo"
    current.operation_id = operation_id
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/tun/confirm", response_model=InstallationRead)
def setup_confirm_tun(session: SessionDep) -> InstallationRead:
    current = get_state(session)
    if current.status != "tun_pending_confirmation" or not current.operation_id:
        raise HTTPException(status_code=409, detail="No TUN change is awaiting confirmation")
    try:
        confirm_mihomo_apply(current.operation_id)
    except HelperError as exc:
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    plan = SetupPlan.model_validate(current.desired_config)
    current.status = "tun_ready" if plan.install_zashboard else "complete"
    current.current_step = "zashboard" if plan.install_zashboard else "complete"
    current.operation_kind = None
    current.operation_id = None
    current.completed_at = None if plan.install_zashboard else datetime.now().astimezone()
    session.commit()
    session.refresh(current)
    return read_state(current)


@router.post("/zashboard/install", response_model=InstallationRead)
def setup_install_zashboard(session: SessionDep) -> InstallationRead:
    current = get_state(session)
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
        mark_failed(current, session, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from None
    current.status = "complete"
    current.current_step = "complete"
    current.completed_at = datetime.now().astimezone()
    session.commit()
    session.refresh(current)
    return read_state(current)
