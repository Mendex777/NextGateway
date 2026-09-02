from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ...db import get_session
from ...models import AuditEvent
from ...schemas import NetworkOperationRead, NetworkPreview
from ...settings import settings
from ...system.client import (
    HelperError,
    begin_network_apply,
    confirm_network_apply,
    network_apply_status,
)
from ...system.network import NetworkConfig, render_netplan, validate_operation_id

router = APIRouter(prefix="/api/v1/system/network", tags=["network"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/preview", response_model=NetworkPreview)
def network_preview(payload: NetworkConfig) -> NetworkPreview:
    return NetworkPreview(
        config=payload,
        netplan_yaml=render_netplan(payload),
        mutations_enabled=settings.system_mutations_enabled,
    )


@router.post("/apply", response_model=NetworkOperationRead)
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


@router.post("/{operation_id}/confirm", response_model=NetworkOperationRead)
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


@router.get("/{operation_id}", response_model=NetworkOperationRead)
def network_status(operation_id: str) -> NetworkOperationRead:
    if not settings.system_mutations_enabled:
        raise HTTPException(status_code=403, detail="System mutations are disabled")
    try:
        operation_id = validate_operation_id(operation_id)
        operation = network_apply_status(operation_id)
    except (HelperError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return NetworkOperationRead(operation_id=operation_id, state=operation["state"])
