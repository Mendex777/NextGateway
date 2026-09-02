from datetime import UTC, datetime
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...db import get_session
from ...models import Node, ProxyGroupMember, SubscriptionNode
from ...schemas import NodeCreate, NodeRead, NodeShare, NodeSummary, NodeUpdate, VlessImportRequest
from ...services.compiler import compile_node
from ...services.hysteria2 import build_hysteria2_uri
from ...services.node_probe import NodeProbeError, probe_node
from ...services.vless import VlessParseError, build_vless_uri, node_fingerprint, parse_vless_uri

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])
SessionDep = Annotated[Session, Depends(get_session)]
_node_import_lock = Lock()


def _unique_node_name(session: Session, desired: str, exclude_id: str | None = None) -> str:
    names = set(
        session.scalars(
            select(Node.name).where(Node.id != exclude_id) if exclude_id else select(Node.name)
        )
    )
    if desired not in names:
        return desired
    suffix = 2
    while True:
        marker = f" ({suffix})"
        candidate = f"{desired[: 255 - len(marker)]}{marker}"
        if candidate not in names:
            return candidate
        suffix += 1


def _save_node(payload: NodeCreate, session: Session) -> Node:
    # Name selection and commit must be serialized. Without this lock, concurrent
    # imports can both observe the same free name and create an invalid Mihomo config.
    with _node_import_lock:
        values = payload.model_dump()
        values["name"] = _unique_node_name(session, payload.name)
        node = Node(**values, fingerprint=node_fingerprint(payload))
        session.add(node)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(status_code=409, detail="This node already exists") from None
        session.refresh(node)
        return node


@router.get("", response_model=list[NodeSummary])
def list_nodes(session: SessionDep) -> list[Node]:
    return list(session.scalars(select(Node).order_by(Node.name)))


@router.delete("/manual/all")
def delete_all_manual_nodes(session: SessionDep) -> dict[str, int]:
    node_ids = list(session.scalars(select(Node.id).where(Node.source == "manual")))
    if not node_ids:
        return {"deleted": 0}
    session.execute(delete(SubscriptionNode).where(SubscriptionNode.node_id.in_(node_ids)))
    session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.node_id.in_(node_ids)))
    session.execute(delete(Node).where(Node.id.in_(node_ids), Node.source == "manual"))
    session.commit()
    return {"deleted": len(node_ids)}


@router.post("/import/vless/preview", response_model=NodeCreate)
def preview_vless(payload: VlessImportRequest) -> NodeCreate:
    try:
        return parse_vless_uri(payload.uri)
    except VlessParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/import/vless", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
def import_vless(payload: VlessImportRequest, session: SessionDep) -> Node:
    try:
        node = parse_vless_uri(payload.uri)
    except VlessParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return _save_node(node, session)


@router.post("", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
def create_node(payload: NodeCreate, session: SessionDep) -> Node:
    return _save_node(payload, session)


@router.get("/{node_id}/share", response_model=NodeShare)
def share_node(node_id: str, session: SessionDep) -> NodeShare:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        uri = build_vless_uri(node) if node.protocol == "vless" else build_hysteria2_uri(node)
        return NodeShare(uri=uri)
    except (VlessParseError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/{node_id}/probe", response_model=NodeSummary)
def probe_single_node(node_id: str, request: Request, session: SessionDep) -> Node:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
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
    session.refresh(node)
    return node


@router.put("/{node_id}", response_model=NodeSummary)
def update_node(node_id: str, payload: NodeUpdate, session: SessionDep) -> Node:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    node.name = _unique_node_name(session, payload.name, exclude_id=node.id)
    node.enabled = payload.enabled
    session.commit()
    session.refresh(node)
    return node


@router.delete("/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(node_id: str, session: SessionDep) -> None:
    node = session.get(Node, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    session.execute(delete(SubscriptionNode).where(SubscriptionNode.node_id == node_id))
    session.execute(delete(ProxyGroupMember).where(ProxyGroupMember.node_id == node_id))
    session.delete(node)
    session.commit()
