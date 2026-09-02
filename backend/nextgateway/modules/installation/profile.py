from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    InstallationState,
    Node,
    ProxyGroup,
    ProxyGroupMember,
    RoutingRule,
    SubscriptionNode,
)
from ...services.compiler import CompileInput, dump_mihomo_yaml
from ...services.subscriptions import SubscriptionParseError
from .schemas import SetupPlan


def configure_default_profile(session: Session, source_ref: str | None = None) -> None:
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


def compile_setup_config(current: InstallationState, session: Session) -> str:
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
