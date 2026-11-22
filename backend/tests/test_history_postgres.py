"""History store tests against a real PostgreSQL: skipped unless VSERVX_TEST_HISTORY_URL is set."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.enums import DatabaseState, InstanceSource
from api.history.maintainer import Maintainer
from api.history.migrate import create_store, inspect_store, store_engine
from api.history.postgres import PostgresStore
from api.history.schema import PARTITIONED, metadata, usage_1m
from api.history.types import Retention, SeriesRef, UsageReading
from api.watch.usage import UsagePoint

RETENTION = Retention(7, 90, 365, 7, 30, 365, 365)
SERIES = SeriesRef("4b6f0c1e-0000-4000-8000-000000000001", InstanceSource.DOCKER, "vllm-a")


async def _store(url: str) -> PostgresStore:
    """A store on a freshly created schema, not started: tests drive its flush and Maintainer."""
    engine = store_engine(url)
    try:
        await create_store(engine)
    finally:
        await engine.dispose()
    return PostgresStore(url, RETENTION, timedelta(minutes=30), 5.0)


def _reading(at: datetime, running: float) -> UsageReading:
    return UsageReading(SERIES, UsagePoint(at, running, None, None, None, None, None))


async def _scalar(engine: AsyncEngine, statement: str) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(statement))).scalar()


def _tables(conn: Connection) -> set[str]:
    return set(inspect(conn).get_table_names())


def _drift(conn: Connection) -> list[object]:
    # Partitions are made by the migration, not declared in the schema.
    def declared(name: str | None, type_: str, parent: dict[str, str | None]) -> bool:
        table = name if type_ == "table" else parent.get("table_name")
        return not (table or "").endswith("_default")

    context = MigrationContext.configure(conn, opts={"include_name": declared})
    return compare_metadata(context, metadata)


def test_new_store_is_created_then_current(history_url: str) -> None:
    async def run() -> None:
        engine = store_engine(history_url)
        try:
            assert (await inspect_store(engine)).state is DatabaseState.NEW
            await create_store(engine)
            schema = await inspect_store(engine)
            async with engine.connect() as conn:
                tables = await conn.run_sync(_tables)
                drift = await conn.run_sync(_drift)
        finally:
            await engine.dispose()

        assert schema.state is DatabaseState.CURRENT and schema.pending == []
        assert {"series", "usage_points", "model_logs", "audit_entries", "rollup_marks"} <= tables
        assert all(f"{name}_default" in tables for name in PARTITIONED)
        assert drift == []

    asyncio.run(run())


def test_rollups_match_raw_after_late_backlog(history_url: str) -> None:
    async def run() -> tuple[int, float]:
        store = await _store(history_url)
        maintainer = Maintainer(store._engine, RETENTION)
        now = datetime.now(UTC)
        minute = now.replace(second=0, microsecond=0) - timedelta(minutes=3)
        try:
            await store._flush([_reading(minute + timedelta(seconds=5 * n), float(n)) for n in range(12)])
            await maintainer.roll_up(now)
            await store._flush([_reading(minute + timedelta(seconds=57), 100.0)])
            await maintainer.roll_up(now)
            async with store._engine.connect() as conn:
                row = (await conn.execute(
                    select(usage_1m.c.n, usage_1m.c.running_avg).where(usage_1m.c.bucket == minute)
                )).one()
        finally:
            await store._engine.dispose()
        return row.n, row.running_avg

    n, running_avg = asyncio.run(run())
    assert n == 13
    assert running_avg == pytest.approx((sum(range(12)) + 100) / 13, rel=1e-5)


def test_retention_drops_old_partitions(history_url: str) -> None:
    async def run() -> tuple[object, object]:
        engine = store_engine(history_url)
        now = datetime.now(UTC)
        old = now - timedelta(days=10)
        name = f"usage_points_p{old:%Y%m%d}"
        try:
            await create_store(engine)
            maintainer = Maintainer(engine, RETENTION)
            await maintainer.ensure_partitions(old)
            before = await _scalar(engine, f"SELECT to_regclass('{name}') IS NOT NULL")
            await maintainer.expire(now)
            after = await _scalar(engine, f"SELECT to_regclass('{name}') IS NOT NULL")
        finally:
            await engine.dispose()
        return before, after

    assert asyncio.run(run()) == (True, False)


def test_partition_created_when_default_holds_rows(history_url: str) -> None:
    async def run() -> tuple[object, object]:
        store = await _store(history_url)
        now = datetime.now(UTC)
        try:
            # No day partitions exist yet, so the reading lands in the default partition.
            await store._flush([_reading(now, 1.0)])
            await Maintainer(store._engine, RETENTION).ensure_partitions(now)
            in_day = await _scalar(store._engine, f"SELECT count(*) FROM usage_points_p{now:%Y%m%d}")
            in_default = await _scalar(store._engine, "SELECT count(*) FROM usage_points_default")
        finally:
            await store._engine.dispose()
        return in_day, in_default

    assert asyncio.run(run()) == (1, 0)
