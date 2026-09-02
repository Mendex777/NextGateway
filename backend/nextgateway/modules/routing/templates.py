import urllib.parse
import urllib.request
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_session
from ...models import ProxyGroup, ProxyGroupGroupMember, RoutingRule, RuleProvider
from ...schemas import (
    RoutingPresetCreate,
    RoutingRuleRead,
    RoutingTemplateImport,
    RoutingTemplatePreview,
)

router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]

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


def _install_service_routing_preset(
    session: Session,
    base_group_id: str,
    service_presets: tuple[tuple[str, str], ...],
    ip_presets: tuple[tuple[str, str, str], ...],
) -> list[RoutingRule]:
    base = session.get(ProxyGroup, base_group_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Base proxy group not found")
    groups_by_name = {item.name: item for item in session.scalars(select(ProxyGroup))}
    providers_by_name = {item.name: item for item in session.scalars(select(RuleProvider))}
    for slug, label in service_presets:
        provider_name = f"service-{slug.replace('!', 'not-')}"
        if provider_name not in providers_by_name:
            session.add(
                RuleProvider(
                    name=provider_name,
                    type="http",
                    behavior="domain",
                    format="mrs",
                    url=(
                        "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/"
                        f"meta/geo/geosite/{slug}.mrs"
                    ),
                    path=f"./rules/{provider_name}.mrs",
                    interval=86400,
                    proxy="DIRECT",
                )
            )
        if label not in groups_by_name:
            group = ProxyGroup(name=label, type="select", enabled=True, include_direct=True)
            group.group_members = [ProxyGroupGroupMember(member_group_id=base.id, position=0)]
            session.add(group)
    for slug, _label, directory in ip_presets:
        provider_name = f"service-{slug}-ip"
        if provider_name not in providers_by_name:
            session.add(
                RuleProvider(
                    name=provider_name,
                    type="http",
                    behavior="ipcidr",
                    format="mrs",
                    url=(
                        "https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/"
                        f"meta/{directory}/{slug}.mrs"
                    ),
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
    for slug, label in service_presets:
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
    for slug, label, _directory in ip_presets:
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
    service_presets = tuple((str(item["id"]), str(item["name"])) for item in data["services"])
    _install_service_routing_preset(session, payload.base_group_id, service_presets, ())
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
    for index, rule in enumerate(existing):
        rule.position = -(index + 1)
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
    base = session.get(ProxyGroup, payload.base_group_id)
    ordered.extend(
        [rule for rule in existing if rule.type == "MATCH"]
        or [
            RoutingRule(
                name="Остальной трафик",
                enabled=True,
                position=0,
                type="MATCH",
                target=base.name,
                source="service-preset",
            )
        ]
    )
    for index, rule in enumerate(ordered):
        rule.position = index * 10
        session.add(rule)
    session.commit()
    return list(session.scalars(select(RoutingRule).order_by(RoutingRule.position)))


@router.post("/routing-presets/services", response_model=list[RoutingRuleRead])
def install_service_routing_preset(
    payload: RoutingPresetCreate, session: SessionDep
) -> list[RoutingRule]:
    return _install_service_routing_preset(
        session,
        payload.base_group_id,
        SERVICE_PRESETS,
        SERVICE_IP_PRESETS,
    )
