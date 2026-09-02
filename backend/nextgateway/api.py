from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .db import get_session

router = APIRouter(prefix="/api/v1")
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scope": "manager-only"}


