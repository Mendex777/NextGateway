import pytest
from nextgateway.settings import settings


@pytest.fixture(autouse=True)
def disable_auth_for_existing_tests(monkeypatch):
    monkeypatch.setattr(settings, "auth_required", False)
