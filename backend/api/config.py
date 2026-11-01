from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, overridable via VSERVX_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="VSERVX_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = Path.home() / ".config" / "vservx"
    # Other origins allowed to call the API with the session cookie. None by default: the built
    # UI is served same-origin, and the Vite dev server proxies /api.
    cors_origins: list[str] = []
    # Sign-in lasts 7 days; a dashboard that signs you out every hour is a nuisance.
    access_token_minutes: int = 10080
    # The built web app (npm run build in ui/), served at "/" when its index.html exists.
    ui_dir: Path = Path(__file__).resolve().parents[2] / "ui" / "dist"
    # First-run admin account, created only while the users table is empty.
    # With no password set, a random one is generated and logged once.
    admin_name: str = "Admin"
    admin_email: str = "admin@example.com"
    admin_password: SecretStr | None = None
    # Seconds allowed per SSH hop to connect and log in.
    ssh_connect_timeout: float = 10.0
    # Watching servers for instances: every tested server, all the time, over one kept-open
    # SSH connection each. Usage and GPUs are read every usage interval; containers are looked
    # for every discovery interval. History stays in memory only.
    watch_enabled: bool = True
    usage_interval_seconds: float = 10.0
    discovery_interval_seconds: float = 60.0
    history_minutes: int = 15
    # Most servers doing SSH work at the same moment.
    watch_concurrency: int = 8

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

    @property
    def jwt_key_path(self) -> Path:
        return self.data_dir / "jwt.key"

    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_minutes)


@lru_cache
def get_settings() -> Settings:
    return Settings()
