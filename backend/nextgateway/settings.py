from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NEXTGATEWAY_", env_file=".env")

    database_url: str = "sqlite:///./nextgateway.db"
    generated_config_path: Path = Path("./var/generated/config.yaml")
    applied_mihomo_config_path: Path = Path("/etc/mihomo/config.yaml")
    system_mutations_enabled: bool = False
    helper_path: Path = Path("/opt/nextgateway/venv/bin/nextgateway-helper")
    mihomo_api_url: str = "http://127.0.0.1:9090"
    mihomo_binary_path: Path = Path("/usr/local/bin/mihomo")
    mihomo_secret_path: Path = Path("/etc/nextgateway/secrets/mihomo-api")
    auth_required: bool = True
    session_hours: int = 12
    frontend_dist: Path = Path("./frontend/dist")
    frontend_next_dist: Path = Path("/opt/nextgateway/source/frontend-next/dist")
    zashboard_dist: Path = Path("./zashboard")
    bootstrap_token_path: Path = Path("/var/lib/nextgateway/bootstrap-token")
    subscription_secret_root: Path = Path("/var/lib/nextgateway/subscriptions")


settings = Settings()
