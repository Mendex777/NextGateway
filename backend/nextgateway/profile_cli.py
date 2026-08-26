import argparse
import json
import os
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from .db import SessionLocal
from .models import Node, ProxyGroup, ProxyGroupMember, RoutingRule
from .services.compiler import CompileInput, dump_mihomo_yaml


def main() -> None:
    parser = argparse.ArgumentParser(prog="nextgateway-profile")
    parser.add_argument("--source-ref", default="provider-primary")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    with SessionLocal() as session:
        nodes = list(
            session.scalars(
                select(Node).where(Node.source_ref == arguments.source_ref, Node.enabled.is_(True))
            )
        )
        if not nodes:
            raise SystemExit("No enabled subscription nodes")
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
            rule = RoutingRule(
                name="Default via VPN",
                position=999,
                type="MATCH",
                value=None,
                target="VPN-Auto",
            )
            session.add(rule)
        else:
            rule.type = "MATCH"
            rule.value = None
            rule.target = "VPN-Auto"
            rule.enabled = True
        session.commit()

        groups = list(
            session.scalars(
                select(ProxyGroup).options(selectinload(ProxyGroup.members))
            )
        )
        rules = list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))
        all_nodes = list(session.scalars(select(Node).order_by(Node.name)))
        config = dump_mihomo_yaml(CompileInput(nodes=all_nodes, groups=groups, rules=rules))

    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(".tmp")
    temporary.write_text(config)
    os.chmod(temporary, 0o600)
    os.replace(temporary, arguments.output)
    print(
        json.dumps(
            {
                "enabled_nodes": len(nodes),
                "group": "VPN-Auto",
                "group_type": "url-test",
                "rules": 1,
                "output": str(arguments.output),
            },
            sort_keys=True,
        )
    )
