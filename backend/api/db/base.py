from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores datetimes as UTC; SQLite drops tzinfo, so it is re-attached on read."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware UTC datetimes")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: UTCDateTime,
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


def str_enum(cls: type[StrEnum]) -> Enum:
    # Store enum values as plain strings; no native enum type or CHECK constraint to migrate.
    return Enum(cls, native_enum=False, create_constraint=False, length=32,
                values_callable=lambda e: [m.value for m in e])
