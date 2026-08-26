from pathlib import Path

from fastapi.testclient import TestClient
from nextgateway.db import Base, get_session
from nextgateway.main import app
from nextgateway.settings import settings
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def test_setup_session_csrf_and_logout(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False}
    )
    testing_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_session():
        with testing_session() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr("nextgateway.main.SessionLocal", testing_session)
    monkeypatch.setattr(settings, "auth_required", True)
    with TestClient(app) as client:
        assert client.get("/api/v1/nodes").status_code == 401
        setup = client.post(
            "/api/v1/auth/setup",
            json={"username": "admin", "password": "correct-horse-battery-staple"},
        )
        assert setup.status_code == 201
        csrf = setup.json()["csrf_token"]
        assert client.get("/api/v1/nodes").status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 403
        logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert logout.status_code == 204
        assert client.get("/api/v1/nodes").status_code == 401
    app.dependency_overrides.clear()
