from datetime import timedelta
from functools import lru_cache
from pathlib import Path

from pydantic import NonNegativeInt, PositiveFloat, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, overridable via VSERVX_* environment variables or a .env file."""

    model_config = SettingsConfigDict(env_prefix="VSERVX_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    # "SERV" (S=5, E=3, R=2, V=5), and clear of vLLM's own default, 8000.
    port: int = 5325
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
    # for every discovery interval. history_minutes of usage stays in memory for live charts.
    watch_enabled: bool = True
    usage_interval_seconds: float = 5.0
    discovery_interval_seconds: float = 60.0
    history_minutes: int = 30
    # Most servers doing SSH work at the same moment.
    watch_concurrency: int = 8
    # The history store: a PostgreSQL database that keeps usage and GPU history, state changes,
    # model logs, the audit and vservx's own log. None: history stays in memory only.
    history_url: SecretStr | None = None
    # Days each kind of history is kept in the store.
    history_raw_days: int = 7
    history_minute_days: int = 90
    history_hour_days: int = 365
    model_log_days: int = 7
    app_log_days: int = 30
    event_days: int = 365
    audit_days: int = 365
    # How often each running instance's output is read into the store.
    log_interval_seconds: float = 15.0
    # How the history store reads, writes and looks after itself.
    # Reads:
    # - each read's time limit, covering getting a connection and running the query
    # - after history_read_failures failed reads in a row, reads skip the store this long
    # - the most state changes one events read returns, newest kept
    history_read_timeout_seconds: PositiveFloat = 3.0
    history_read_failures: PositiveInt = 3
    history_read_pause_seconds: PositiveFloat = 30.0
    history_event_limit: PositiveInt = 2000
    # Connecting:
    # - each attempt's time limit, and the wait between attempts while the store is unreachable
    #   or waits for an upgrade
    # - connections kept open to the store
    history_connect_timeout_seconds: PositiveFloat = 10.0
    history_retry_seconds: PositiveFloat = 30.0
    history_pool_size: PositiveInt = 5
    # Writing:
    # - the queue's size while the store can't be reached; the oldest records are dropped beyond it
    # - records per batch, and seconds between flushes (a full batch flushes at once)
    # - the wait after a failed flush, doubling from min to max
    # - how long shutdown waits for the queue to flush
    history_queue_mb: PositiveInt = 64
    history_batch_size: PositiveInt = 1000
    history_flush_seconds: PositiveFloat = 2.0
    history_backoff_min_seconds: PositiveFloat = 1.0
    history_backoff_max_seconds: PositiveFloat = 60.0
    history_stop_flush_seconds: PositiveFloat = 5.0
    # Upkeep:
    # - day partitions made ahead of today
    # - rows deleted per table on each expiry run, outside whole-day partitions
    # - seconds between partition and rollup runs, and between expiry runs
    # - rollup buckets computed per run, so a backlog is caught up in short transactions
    history_partition_days_ahead: NonNegativeInt = 2
    history_delete_batch: PositiveInt = 10000
    history_maintain_seconds: PositiveFloat = 60.0
    history_expire_seconds: PositiveFloat = 3600.0
    history_rollup_buckets: PositiveInt = 1440

    @field_validator("history_url", mode="before")
    @classmethod
    def _postgres_only(cls, value: object) -> object:
        # An empty value (VSERVX_HISTORY_URL= in compose) means no store.
        if value is None or value == "":
            return None
        url = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        if not url.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                "VSERVX_HISTORY_URL must start with postgresql:// (PostgreSQL is the only supported history store)"
            )
        return value

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
