from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from api.enums import AuthType, LaunchType, SnapshotTrigger
from api.models import Server, Snapshot
from api.schemas import (
    ActionHistoryBase,
    ActionHistoryCreate,
    ActionHistoryRead,
    InstanceBase,
    InstanceCreate,
    InstanceRead,
    InstanceUpdate,
    ServerBase,
    ServerCreate,
    ServerRead,
    ServerUpdate,
    SnapshotBase,
    SnapshotCreate,
    SnapshotDetail,
    SnapshotRead,
)

BASE = {"name": "gpu-1", "host": "10.0.0.1", "username": "ubuntu"}


def test_server_create_password_auth() -> None:
    server = ServerCreate(**BASE, auth_type="password", password="hunter2")
    assert server.port == 22
    assert server.password is not None
    assert server.password.get_secret_value() == "hunter2"
    assert "hunter2" not in repr(server)


def test_server_create_key_auth() -> None:
    server = ServerCreate(**BASE, auth_type="key", key_path="~/.ssh/id_ed25519")
    assert server.key_passphrase is None


@pytest.mark.parametrize(
    "fields",
    [
        {"auth_type": "password"},
        {"auth_type": "password", "password": "x", "key_path": "~/.ssh/id"},
        {"auth_type": "key"},
        {"auth_type": "key", "key_path": "~/.ssh/id", "password": "x"},
        {"auth_type": "password", "password": "x", "port": 70000},
        {"auth_type": "password", "password": "x", "name": "   "},
    ],
)
def test_server_create_rejects_invalid(fields: dict) -> None:
    with pytest.raises(ValidationError):
        ServerCreate(**(BASE | fields))


def test_server_update_is_partial() -> None:
    update = ServerUpdate(host="10.0.0.2", key_passphrase=None)
    assert update.model_dump(exclude_unset=True) == {"host": "10.0.0.2", "key_passphrase": None}


def test_server_update_rejects_null_required() -> None:
    with pytest.raises(ValidationError):
        ServerUpdate(name=None)


def test_server_read_hides_secrets() -> None:
    now = datetime.now(UTC)
    server = Server(id=1, **BASE, port=22, auth_type=AuthType.PASSWORD, password="hunter2",
                    created_at=now, updated_at=now)

    data = ServerRead.model_validate(server).model_dump()

    assert data["has_password"] is True
    assert data["has_key_passphrase"] is False
    assert "password" not in data
    assert "hunter2" not in str(data)


def test_schemas_extend_base() -> None:
    assert issubclass(ServerCreate, ServerBase)
    assert issubclass(ServerUpdate, ServerBase)
    assert issubclass(ServerRead, ServerBase)
    assert issubclass(InstanceCreate, InstanceBase)
    assert issubclass(InstanceUpdate, InstanceBase)
    assert issubclass(InstanceRead, InstanceBase)
    assert issubclass(SnapshotCreate, SnapshotBase)
    assert issubclass(SnapshotRead, SnapshotBase)
    assert issubclass(ActionHistoryCreate, ActionHistoryBase)
    assert issubclass(ActionHistoryRead, ActionHistoryBase)


@pytest.mark.parametrize("schema", [ServerUpdate, InstanceUpdate])
def test_update_schemas_are_fully_optional(schema: type[BaseModel]) -> None:
    # Guards against a required field added to a Base but not overridden in its Update.
    required = [name for name, field in schema.model_fields.items() if field.is_required()]
    assert required == [], f"{schema.__name__} has required fields: {required}"


@pytest.mark.parametrize(
    "schema", [ServerRead, InstanceRead, SnapshotRead, SnapshotDetail, ActionHistoryRead]
)
def test_read_schemas_mark_every_field_required(schema: type[BaseModel]) -> None:
    # Responses always include every field, so generated frontend types shouldn't mark any optional.
    json_schema = schema.model_json_schema(mode="serialization")
    assert set(json_schema["required"]) == set(json_schema["properties"])


def test_server_read_and_update_have_no_secret_values() -> None:
    assert "password" not in ServerRead.model_fields
    assert "key_passphrase" not in ServerRead.model_fields
    assert "password" in ServerUpdate.model_fields


def test_instance_create_and_partial_update() -> None:
    created = InstanceCreate(server_id=1, launch_type="docker", ref="abc123", port=8000)
    assert created.status == "unknown"
    assert created.managed is False

    update = InstanceUpdate(status="running")
    assert update.model_dump(exclude_unset=True) == {"status": "running"}

    with pytest.raises(ValidationError):
        InstanceUpdate(status=None)


def test_snapshot_create_builds_model() -> None:
    data = SnapshotCreate(server_id=1, trigger="manual", launch_type="bare",
                          command="vllm serve m", raw="...")
    snapshot = Snapshot(**data.model_dump())
    assert snapshot.trigger is SnapshotTrigger.MANUAL
    assert snapshot.raw == "..."


def test_action_history_create() -> None:
    entry = ActionHistoryCreate(server_id=1, instance_id=None, action="stop", result="ok")
    assert entry.detail is None


def test_snapshot_read_omits_raw() -> None:
    snapshot = Snapshot(id=1, server_id=1, created_at=datetime.now(UTC),
                        trigger=SnapshotTrigger.MANUAL, launch_type=LaunchType.DOCKER,
                        raw='{"Id": "abc"}')

    assert "raw" not in SnapshotRead.model_validate(snapshot).model_dump()
    assert SnapshotDetail.model_validate(snapshot).raw == '{"Id": "abc"}'
