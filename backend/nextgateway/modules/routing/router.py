from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ...db import get_session
from ...models import (
    Node,
    ProxyGroup,
    ProxyGroupGroupMember,
    ProxyGroupMember,
    RoutingRule,
    RuleProvider,
)
from ...schemas import (
    ProxyGroupCreate,
    ProxyGroupRead,
    RoutingRuleCreate,
    RoutingRuleOrder,
    RoutingRuleRead,
    RuleProviderCreate,
    RuleProviderRead,
)

router = APIRouter(prefix="/api/v1", tags=["routing"])
SessionDep = Annotated[Session, Depends(get_session)]


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
