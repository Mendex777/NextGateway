from datetime import datetime

from sqlalchemy.orm import Session

from ...models import InstallationState
from ...settings import settings
from .environment import environment
from .schemas import InstallationRead


def get_state(session: Session) -> InstallationState:
    current = session.get(InstallationState, 1)
    if current is None:
        current = InstallationState(id=1)
        session.add(current)
        session.commit()
        session.refresh(current)
    return current


def reconcile(current: InstallationState, session: Session) -> InstallationState:
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


def read_state(current: InstallationState) -> InstallationRead:
    return InstallationRead(
        status=current.status,
        current_step=current.current_step,
        desired_config=current.desired_config,
        last_error=current.last_error,
        operation_kind=current.operation_kind,
        operation_id=current.operation_id,
        completed_at=current.completed_at,
        environment=environment(),
    )


def mark_failed(current: InstallationState, session: Session, exc: Exception) -> None:
    current.status = "failed"
    current.last_error = str(exc)
    session.commit()
