from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Node, ProxyGroup, ProxyGroupMember, Subscription, SubscriptionNode
from .subscription_fetch import fetch_subscription_response
from .subscription_metadata import parse_subscription_metadata
from .subscription_source import read_subscription_source
from .subscriptions import parse_subscription, sync_nodes


def refresh_subscription(session: Session, subscription: Subscription) -> Subscription:
    source = read_subscription_source(Path(subscription.secret_ref))
    response = fetch_subscription_response(source.url, source.headers)
    parsed = parse_subscription(response.content)
    metadata = parse_subscription_metadata(response.headers)
    sync_nodes(session, parsed, subscription.id)
    auto_group = session.scalar(select(ProxyGroup).where(ProxyGroup.name == "VPN-Auto"))
    if auto_group:
        linked_ids = list(
            session.scalars(
                select(Node.id)
                .join(SubscriptionNode, SubscriptionNode.node_id == Node.id)
                .where(SubscriptionNode.subscription_id == subscription.id)
                .order_by(SubscriptionNode.position)
            )
        )
        current_ids = {member.node_id for member in auto_group.members}
        next_position = max((member.position for member in auto_group.members), default=-1) + 1
        for node_id in linked_ids:
            if node_id not in current_ids:
                session.add(
                    ProxyGroupMember(
                        group_id=auto_group.id, node_id=node_id, position=next_position
                    )
                )
                next_position += 1
    now = datetime.now(UTC)
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
    session.commit()
    session.refresh(subscription)
    return subscription


def refresh_due_subscriptions(session: Session) -> int:
    now = datetime.now(UTC)
    refreshed = 0
    subscriptions = list(
        session.scalars(select(Subscription).where(Subscription.enabled.is_(True)))
    )
    for subscription in subscriptions:
        last_update = subscription.last_update
        if last_update and last_update.tzinfo is None:
            last_update = last_update.replace(tzinfo=UTC)
        if last_update and last_update + timedelta(seconds=subscription.update_interval) > now:
            continue
        try:
            refresh_subscription(session, subscription)
        except Exception as exc:  # scheduler records provider/network failures and continues
            session.rollback()
            current = session.get(Subscription, subscription.id)
            if current:
                current.last_update = now
                current.last_error = str(exc)[:2048]
                session.commit()
        refreshed += 1
    return refreshed
