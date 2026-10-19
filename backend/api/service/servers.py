from typing import Any

from pydantic import SecretStr

from api.models import Server
from api.schemas import ServerCreate, ServerUpdate
from api.schemas.server import check_auth_fields

_AUTH_FIELDS = ("auth_type", "password", "key_path", "key_passphrase")


def _reveal(fields: dict[str, Any]) -> dict[str, Any]:
    """Unwrap SecretStr values so the model stores the secret, not its masked form."""
    return {name: value.get_secret_value() if isinstance(value, SecretStr) else value
            for name, value in fields.items()}


def server_from_create(data: ServerCreate) -> Server:
    return Server(**_reveal(data.model_dump()))


def apply_server_update(server: Server, update: ServerUpdate) -> None:
    """Apply a partial update. Raises ValueError, leaving the server unchanged, if the
    merged credentials don't match auth_type."""
    fields = _reveal(update.model_dump(exclude_unset=True))
    merged = {name: fields.get(name, getattr(server, name)) for name in _AUTH_FIELDS}
    check_auth_fields(**merged)
    for name, value in fields.items():
        setattr(server, name, value)
