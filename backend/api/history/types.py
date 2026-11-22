"""What the history store keeps and serves, and the seam every store implements.

- Store rows name servers, workspaces and users by uid, never by SQLite id.
- Times are timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from api.enums import DatabaseState, InstanceSource, StoreState
from api.watch.usage import UsagePoint

if TYPE_CHECKING:
    from api.config import Settings


@dataclass(frozen=True)
class SeriesRef:
    """One instance's identity in the store."""

    server_uid: str
    source: InstanceSource
    name: str


@dataclass(frozen=True)
class Span:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Retention:
    """How many days each kind of history is kept."""

    raw_days: int
    minute_days: int
    hour_days: int
    model_log_days: int
    app_log_days: int
    event_days: int
    audit_days: int

    @classmethod
    def from_settings(cls, settings: Settings) -> Retention:
        return cls(
            raw_days=settings.history_raw_days,
            minute_days=settings.history_minute_days,
            hour_days=settings.history_hour_days,
            model_log_days=settings.model_log_days,
            app_log_days=settings.app_log_days,
            event_days=settings.event_days,
            audit_days=settings.audit_days,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "raw": self.raw_days,
            "minute": self.minute_days,
            "hour": self.hour_days,
            "model_logs": self.model_log_days,
            "app_logs": self.app_log_days,
            "events": self.event_days,
            "audit": self.audit_days,
        }


# Records


@dataclass(frozen=True)
class UsageReading:
    series: SeriesRef
    point: UsagePoint


@dataclass(frozen=True)
class GpuReading:
    server_uid: str
    at: datetime
    index: int
    utilization: float | None
    memory_used: float | None
    memory_total: float | None
    temperature: float | None


@dataclass(frozen=True)
class StateChange:
    """A server's state change (series None) or an instance's.

    - from_state None: first seen.
    - to_state None: removed.
    """

    server_uid: str
    series: SeriesRef | None
    at: datetime
    from_state: str | None
    to_state: str | None
    message: str | None


@dataclass(frozen=True)
class LogCursor:
    """Where reading a series' log resumes.

    - at: time of the newest line read; None before the first read.
    - at_count: how many lines at exactly that time were already read.
    - journal: journalctl's cursor, for systemd services.
    """

    at: datetime | None
    at_count: int = 0
    journal: str | None = None


@dataclass(frozen=True)
class LogLine:
    at: datetime
    stream: str
    level: str | None
    # One of vLLM's per-request lines, which can include prompts.
    request: bool
    text: str
    # Orders lines that share a time.
    seq: int = 0


@dataclass(frozen=True)
class LogLines:
    series: SeriesRef
    lines: tuple[LogLine, ...]
    cursor: LogCursor


@dataclass(frozen=True)
class AuditEntry:
    """Who did what. The user's name and email are copied, so the entry outlives the account."""

    at: datetime
    action: str
    result: str
    user_uid: str | None
    user_name: str | None
    user_email: str | None
    workspace_uid: str | None
    server_uid: str | None
    client_ip: str | None
    target: str | None
    detail: dict[str, Any]


@dataclass(frozen=True)
class AppLogEntry:
    """One record of vservx's own log."""

    at: datetime
    level: str
    logger: str
    message: str
    exception: str | None


Record = UsageReading | GpuReading | StateChange | LogLines | AuditEntry | AppLogEntry


# Reads


@dataclass(frozen=True)
class UsageSeries:
    points: list[UsagePoint]
    resolution_seconds: float
    # Served from memory because the store couldn't answer.
    degraded: bool


@dataclass(frozen=True)
class GpuPoint:
    at: datetime
    utilization: float | None
    memory_used: float | None
    memory_total: float | None
    temperature: float | None


@dataclass(frozen=True)
class GpuSeries:
    index: int
    points: list[GpuPoint]


@dataclass(frozen=True)
class GpuHistory:
    gpus: list[GpuSeries]
    resolution_seconds: float
    degraded: bool


@dataclass(frozen=True)
class LogQuery:
    span: Span
    # The lowest level to include.
    level: str | None
    text: str | None
    before: str | None
    limit: int


@dataclass(frozen=True)
class LogPage:
    lines: list[LogLine]
    next_before: str | None


@dataclass(frozen=True)
class AuditQuery:
    span: Span
    action: str | None
    user_uid: str | None
    workspace_uid: str | None
    before: str | None
    limit: int


@dataclass(frozen=True)
class AuditPage:
    entries: list[AuditEntry]
    next_before: str | None


@dataclass(frozen=True)
class AppLogQuery:
    span: Span
    level: str | None
    logger: str | None
    text: str | None
    before: str | None
    limit: int


@dataclass(frozen=True)
class AppLogPage:
    entries: list[AppLogEntry]
    next_before: str | None


@dataclass(frozen=True)
class ResumePoint:
    """What a server's watch needs to carry on where the last run stopped.

    Dict keys are api.watch.frameworks.instance_key(source, name).
    """

    server_state: str | None
    instance_states: dict[str, str]
    log_cursors: dict[str, LogCursor]


@dataclass(frozen=True)
class StoreSchema:
    state: DatabaseState
    current_revision: str | None
    head_revision: str
    pending: list[str]


@dataclass(frozen=True)
class StoreStatus:
    persistent: bool
    state: StoreState
    retention: Retention
    queued: int
    # Records dropped, by reason.
    dropped: dict[str, int]
    last_error: str | None
    last_write_at: datetime | None


class HistoryRequired(Exception):
    """The read needs a history store, and none is set."""


class HistoryUnavailable(Exception):
    """The history store can't answer right now."""


class HistoryStore(Protocol):
    persistent: bool

    def status(self) -> StoreStatus: ...
    def schema(self) -> StoreSchema | None: ...
    async def upgrade(self) -> bool: ...
    # Thread-safe; never blocks and never raises.
    def write(self, record: Record) -> None: ...
    def forget_server(self, server_uid: str) -> None: ...
    def forget_request_lines(self, server_uid: str) -> None: ...
    async def usage(self, series: SeriesRef, span: Span, max_points: int) -> UsageSeries: ...
    async def gpus(self, server_uid: str, span: Span, max_points: int) -> GpuHistory: ...
    async def events(self, server_uid: str, span: Span, series: SeriesRef | None) -> list[StateChange]: ...
    async def logs(self, series: SeriesRef, query: LogQuery) -> LogPage: ...
    async def audit(self, query: AuditQuery) -> AuditPage: ...
    async def app_logs(self, query: AppLogQuery) -> AppLogPage: ...
    async def resume(self, server_uid: str) -> ResumePoint: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
