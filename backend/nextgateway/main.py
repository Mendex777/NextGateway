import asyncio
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from . import models  # noqa: F401
from .api import router
from .auth import COOKIE_NAME, token_hash
from .auth import router as auth_router
from .db import Base, SessionLocal, engine
from .models import AuthSession
from .modules.nodes import router as nodes_router
from .modules.routing import router as routing_router
from .modules.subscriptions import router as subscriptions_router
from .services.subscription_manager import refresh_due_subscriptions
from .settings import settings
from .setup import router as setup_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(engine)
    async def subscription_scheduler():
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(_refresh_subscriptions)

    task = asyncio.create_task(subscription_scheduler())
    try:
        yield
    finally:
        task.cancel()


def _refresh_subscriptions() -> None:
    with SessionLocal() as session:
        refresh_due_subscriptions(session)


def _not_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC)


app = FastAPI(title="NextGateway API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def authentication(request: Request, call_next):
    path = request.url.path
    public_api = path in {
        "/api/v1/auth/status",
        "/api/v1/auth/setup",
        "/api/v1/auth/login",
    }
    current = None
    raw_token = request.cookies.get(COOKIE_NAME)
    if settings.auth_required and raw_token:
        with SessionLocal() as session:
            current = session.scalar(
                select(AuthSession)
                .options(selectinload(AuthSession.user))
                .where(AuthSession.token_hash == token_hash(raw_token))
            )
            if current and (not _not_expired(current.expires_at) or not current.user.enabled):
                session.delete(current)
                session.commit()
                current = None
            elif current:
                current.last_seen_at = datetime.now(UTC)
                session.commit()
                session.expunge(current)
    if current:
        request.state.auth_session = current
    protected_api = path.startswith("/api/") and not public_api
    if settings.auth_required and protected_api:
        if current is None:
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            csrf = request.headers.get("X-CSRF-Token")
            if csrf is None or not secrets.compare_digest(csrf, current.csrf_token):
                return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)
    return await call_next(request)


app.include_router(auth_router)
app.include_router(router)
app.include_router(nodes_router)
app.include_router(routing_router)
app.include_router(subscriptions_router)
app.include_router(setup_router)

zashboard = settings.zashboard_dist
app.mount(
    "/dashboard",
    StaticFiles(directory=zashboard, html=True, check_dir=False),
    name="zashboard",
)

frontend = settings.frontend_dist
if frontend.exists():
    assets = frontend / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path in {"next", "next/"}:
            return RedirectResponse(url="/", status_code=308)
        candidate = (frontend / path).resolve()
        if path and candidate.is_file() and frontend.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(frontend / "index.html")
