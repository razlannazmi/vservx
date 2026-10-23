from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from api.enums import ConnectionFailure


class HopResult(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    # None for the unsaved server in a test of settings before saving.
    server_id: int | None
    name: str
    ok: bool
    # The host key the server presented, when the handshake got that far.
    fingerprint: str | None
    reason: ConnectionFailure | None
    message: str | None


class ConnectionTestResult(BaseModel):
    """A failed test is a normal result (ok false), not an HTTP error."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    ok: bool
    hostname: str | None
    elapsed_ms: int
    # Every hop attempted, outermost jump host first; on failure the failing hop is last.
    hops: list[HopResult]


class HostKeyAccept(BaseModel):
    # The fingerprint the admin saw in the failed test; stored only if the server still presents it.
    fingerprint: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
