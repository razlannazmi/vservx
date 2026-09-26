from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, overridable via VSERVX_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="VSERVX_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path.home() / ".config" / "vservx"
    # Vite dev server origin; the built UI is served same-origin in production.
    cors_origins: list[str] = ["http://localhost:5173"]

    @field_validator("data_dir")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        # Path does not expand "~", so VSERVX_DATA_DIR=~/x would create a literal "~" folder.
        return value.expanduser()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vservx.db"

    @property
    def secret_key_path(self) -> Path:
        return self.data_dir / "secret.key"


@lru_cache
def get_settings() -> Settings:
    return Settings()
