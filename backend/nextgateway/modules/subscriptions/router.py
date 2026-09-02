import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db import get_session
from ...models import Node, ProxyGroupMember, Subscription, SubscriptionNode
from ...schemas import (
    NodeSummary,
    SubscriptionCreate,
    SubscriptionDetail,
    SubscriptionRead,
    SubscriptionShare,
    SubscriptionUpdate,
)
from ...services.compiler import compile_node
from ...services.node_probe import NodeProbeError, probe_node
from ...services.subscription_fetch import SubscriptionFetchError
from ...services.subscription_manager import refresh_subscription as refresh_subscription_data
from ...services.subscription_source import read_subscription_source, write_subscription_source
from ...services.subscriptions import SubscriptionParseError
from ...settings import settings

router = APIRouter(prefix="/api/v1/subscriptions", tags=["subscriptions"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("", response_model=list[SubscriptionRead])
def list_subscriptions(session: SessionDep) -> list[Subscription]:
    return list(session.scalars(select(Subscription).order_by(Subscription.name)))


@router.post("", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
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


@router.get("/{subscription_id}", response_model=SubscriptionDetail)
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


@router.get("/{subscription_id}/share", response_model=SubscriptionShare)
def share_subscription(subscription_id: str, session: SessionDep) -> SubscriptionShare:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        return SubscriptionShare(url=read_subscription_source(Path(subscription.secret_ref)).url)
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Subscription URL is unavailable") from exc


@router.put("/{subscription_id}", response_model=SubscriptionRead)
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


@router.post("/{subscription_id}/refresh", response_model=SubscriptionRead)
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


@router.post("/{subscription_id}/probe", response_model=list[NodeSummary])
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


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
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
