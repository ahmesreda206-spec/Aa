from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


def persistent_secret() -> str:
    """Create a stable local key without committing secrets to source control."""
    key_path = ROOT_DIR / "data" / ".session-secret"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(64)
    key_path.write_text(value, encoding="utf-8")
    key_path.chmod(0o600)
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_prefix="QWEN_", extra="ignore"
    )

    app_name: str = "Qwen Farm v2"
    environment: str = "production"
    database_url: str = f"sqlite:///{ROOT_DIR / 'data' / 'qwen.db'}"
    secret_key: str = Field(default_factory=persistent_secret)
    jwt_issuer: str = "qwen-farm-v2"
    jwt_audience: str = "qwen-farm-operators"
    session_minutes: int = 30
    cookie_secure: bool = True
    cors_origins: str = ""
    allowed_hosts: str = "*"
    bootstrap_token: str = ""
    max_body_bytes: int = 1_048_576
    ai_enabled: bool = False
    ai_base_path: str = str(ROOT_DIR / "models" / "llama_14b_base")
    ai_adapter_path: str = str(ROOT_DIR / "models" / "llama_14b_lora")
    ai_max_new_tokens: int = 384
    ai_temperature: float = 0.2

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def session_cookie(self) -> str:
        return "__Host-qwen_session" if self.cookie_secure else "qwen_session"

    @property
    def csrf_cookie(self) -> str:
        return "__Host-qwen_csrf" if self.cookie_secure else "qwen_csrf"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
