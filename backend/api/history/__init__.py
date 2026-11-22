"""The history store: usage and GPU history, state changes, model logs, audit and vservx's own log."""

from datetime import timedelta

from api.config import Settings
from api.history.memory import MemoryStore
from api.history.types import HistoryStore, Retention, StoreTuning


def open_store(settings: Settings) -> HistoryStore:
    """The store settings ask for: PostgreSQL with VSERVX_HISTORY_URL, memory only without it."""
    retention = Retention.from_settings(settings)
    window = timedelta(minutes=settings.history_minutes)
    if settings.history_url is None:
        return MemoryStore(window, settings.usage_interval_seconds, retention)
    # Imported here so a vservx without a store never loads the PostgreSQL code.
    from api.history.postgres import PostgresStore

    return PostgresStore(settings.history_url.get_secret_value(), retention, StoreTuning.from_settings(settings),
                         window, settings.usage_interval_seconds)


__all__ = ["HistoryStore", "MemoryStore", "open_store"]
