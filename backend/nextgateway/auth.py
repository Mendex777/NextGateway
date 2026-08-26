import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .api import SessionDep
from .models import AuthSession, LocalUser
from .settings import settings

COOKIE_NAME = "nextgateway_session"
password_hasher = PasswordHasher()
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    setup_token: str | None = Field(default=None, min_length=32, max_length=256)


class AuthState(BaseModel):
    setup_required: bool
    authenticated: bool
    username: str | None = None
    csrf_token: str | None = None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user: LocalUser, session: Session, response: Response) -> AuthSession:
    raw_token = secrets.token_urlsafe(48)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        csrf_token=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.session_hours),
    )
    session.add(auth_session)
    session.commit()
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        httponly=True,
        secure=False,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    return auth_session


@router.get("/status", response_model=AuthState)
def auth_status(request: Request, session: SessionDep) -> AuthState:
    user_count = session.scalar(select(func.count()).select_from(LocalUser)) or 0
    current = getattr(request.state, "auth_session", None)
    return AuthState(
        setup_required=user_count == 0,
        authenticated=current is not None,
        username=current.user.username if current else None,
        csrf_token=current.csrf_token if current else None,
    )


@router.post("/setup", response_model=AuthState, status_code=status.HTTP_201_CREATED)
def setup(payload: Credentials, response: Response, session: SessionDep) -> AuthState:
    if (session.scalar(select(func.count()).select_from(LocalUser)) or 0) != 0:
        raise HTTPException(status_code=409, detail="Initial setup is already complete")
    token_path = settings.bootstrap_token_path
    if token_path.exists():
        expected_token = token_path.read_text().strip()
        if payload.setup_token is None or not secrets.compare_digest(
            payload.setup_token, expected_token
        ):
            raise HTTPException(status_code=403, detail="Invalid bootstrap token")
    user = LocalUser(
        username=payload.username,
        password_hash=password_hasher.hash(payload.password),
    )
    session.add(user)
    session.flush()
    current = create_session(user, session, response)
    token_path.unlink(missing_ok=True)
    return AuthState(
        setup_required=False,
        authenticated=True,
        username=user.username,
        csrf_token=current.csrf_token,
    )


@router.post("/login", response_model=AuthState)
def login(payload: Credentials, response: Response, session: SessionDep) -> AuthState:
    user = session.scalar(select(LocalUser).where(LocalUser.username == payload.username))
    if user is None or not user.enabled:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    try:
        password_hasher.verify(user.password_hash, payload.password)
    except VerifyMismatchError:
        raise HTTPException(status_code=401, detail="Invalid username or password") from None
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(payload.password)
    current = create_session(user, session, response)
    return AuthState(
        setup_required=False,
        authenticated=True,
        username=user.username,
        csrf_token=current.csrf_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, session: SessionDep) -> None:
    raw_token = request.cookies.get(COOKIE_NAME)
    if raw_token:
        session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(raw_token)))
        session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
