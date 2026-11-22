"""The history store's write queue: records wait here, in order, until a batch reaches the store.

- The queue is bounded by an estimate of its size. When full, the oldest records are dropped and
  counted by kind; forget operations are never dropped.
- A flush that fails because the store can't be reached keeps its batch and backs off.
- A flush the store rejects for its content drops that batch, so one bad row can't block the queue.
"""

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

from api.db.base import utcnow
from api.history.types import AppLogEntry, AuditEntry, GpuReading, LogLines, Record, StateChange, UsageReading

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ForgetServer:
    """Delete everything stored for a server, except its audit."""

    server_uid: str


@dataclass(frozen=True)
class ForgetRequestLines:
    """Delete a server's stored request lines."""

    server_uid: str


Queued = Record | ForgetServer | ForgetRequestLines
Flush = Callable[[Sequence[Queued]], Awaitable[None]]


class ConnectionLost(Exception):
    """A flush failed because the store couldn't be reached; its batch is kept for a retry."""


# Estimated size of a record that isn't log text.
SMALL_RECORD_BYTES = 200
MIN_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0


def kind_of(item: Queued) -> str:
    match item:
        case UsageReading():
            return "usage"
        case GpuReading():
            return "gpu"
        case StateChange():
            return "event"
        case LogLines():
            return "model_logs"
        case AuditEntry():
            return "audit"
        case AppLogEntry():
            return "app_logs"
        case _:
            return "control"


def _size(item: Queued) -> int:
    if isinstance(item, LogLines):
        return max(1, sum(len(line.text) for line in item.lines))
    if isinstance(item, AppLogEntry):
        return max(1, len(item.message) + len(item.exception or ""))
    return SMALL_RECORD_BYTES


def _server_uid(item: Queued) -> str | None:
    """The server a record belongs to, for dropping records of a forgotten server.

    Audit entries are left out: they outlive the server they name.
    """
    match item:
        case UsageReading() | LogLines():
            return item.series.server_uid
        case GpuReading() | StateChange():
            return item.server_uid
        case _:
            return None


def _is_control(item: Queued) -> bool:
    return isinstance(item, ForgetServer | ForgetRequestLines)


class Writer:
    def __init__(self, flush: Flush, *, max_bytes: int = 64 * 1024 * 1024, batch_size: int = 1000,
                 interval: float = 2.0) -> None:
        self._flush = flush
        self._max_bytes = max_bytes
        self._batch_size = batch_size
        self._interval = interval
        self._lock = threading.Lock()
        self._items: deque[tuple[Queued, int]] = deque()
        self._bytes = 0
        self._in_flight = 0
        self._forgotten: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._logged: set[type[BaseException]] = set()
        # While true, nothing is flushed and records wait (or are dropped once the queue fills).
        self.paused = False
        # True after a flush failed to reach the store, until one succeeds.
        self.retrying = False
        self.dropped: dict[str, int] = {}
        self.last_error: str | None = None
        self.last_write_at: datetime | None = None

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._items) + self._in_flight

    def put(self, item: Queued) -> None:
        """Queue a record or forget operation. Thread-safe; never blocks."""
        with self._lock:
            if isinstance(item, ForgetServer):
                self._forgotten.add(item.server_uid)
            elif (uid := _server_uid(item)) is not None and uid in self._forgotten:
                return
            size = _size(item)
            self._items.append((item, size))
            self._bytes += size
            self._trim()
            full = len(self._items) >= self._batch_size
        if full:
            self._wake_soon()

    async def run(self) -> None:
        """Flush every `interval`, or sooner once a batch is full, until cancelled."""
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        backoff = MIN_BACKOFF_SECONDS
        while True:
            try:
                async with asyncio.timeout(self._interval):
                    await self._wake.wait()
            except TimeoutError:
                pass
            self._wake.clear()
            while not self.paused and (entries := self._take()):
                if await self._send(entries):
                    backoff = MIN_BACKOFF_SECONDS
                else:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)

    async def drain(self, timeout: float) -> int:
        """Flush what's queued, for at most `timeout` seconds. Returns how many records are left unwritten."""
        try:
            async with asyncio.timeout(timeout):
                while not self.paused and (entries := self._take()):
                    if not await self._send(entries):
                        break
        except TimeoutError:
            pass
        return self.queued

    async def _send(self, entries: list[tuple[Queued, int]]) -> bool:
        """Flush one batch. False when the store couldn't be reached and the batch went back on the queue."""
        try:
            await self._flush([item for item, _ in entries])
        except ConnectionLost as exc:
            self._give_back(entries)
            self.retrying = True
            self.last_error = str(exc) or "History store unreachable"
            return False
        except asyncio.CancelledError:
            self._give_back(entries)
            raise
        except Exception as exc:
            self._finish()
            with self._lock:
                for item, _ in entries:
                    if not _is_control(item):
                        self._count_dropped(item)
            self.last_error = f"{type(exc).__name__}: {exc}"
            if type(exc) not in self._logged:
                self._logged.add(type(exc))
                logger.warning("The history store rejected %d records, which were dropped: %s", len(entries), exc)
            return True
        self._finish()
        self.retrying = False
        self.last_error = None
        self.last_write_at = utcnow()
        return True

    def _take(self) -> list[tuple[Queued, int]]:
        with self._lock:
            entries = [self._items.popleft() for _ in range(min(self._batch_size, len(self._items)))]
            self._bytes -= sum(size for _, size in entries)
            self._in_flight = len(entries)
            return entries

    def _give_back(self, entries: list[tuple[Queued, int]]) -> None:
        with self._lock:
            self._items.extendleft(reversed(entries))
            self._bytes += sum(size for _, size in entries)
            self._in_flight = 0
            self._trim()

    def _finish(self) -> None:
        with self._lock:
            self._in_flight = 0

    def _trim(self) -> None:
        """Drop the oldest records until the queue fits. Caller holds the lock."""
        controls: list[tuple[Queued, int]] = []
        while self._bytes > self._max_bytes and self._items:
            item, size = self._items.popleft()
            if _is_control(item):
                controls.append((item, size))
                continue
            self._bytes -= size
            self._count_dropped(item)
        self._items.extendleft(reversed(controls))

    def _count_dropped(self, item: Queued) -> None:
        kind = kind_of(item)
        self.dropped[kind] = self.dropped.get(kind, 0) + 1

    def _wake_soon(self) -> None:
        loop, wake = self._loop, self._wake
        if loop is None or wake is None:
            return
        try:
            loop.call_soon_threadsafe(wake.set)
        except RuntimeError:
            # The loop has closed: the store is stopping.
            pass
