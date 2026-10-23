from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from api.schemas.server import Text255

# Room for any real key (a 16384-bit RSA PEM is under 13,000 characters); larger input is
# rejected before it's parsed.
PrivateKeyText = Annotated[SecretStr, Field(min_length=1, max_length=16384)]
Passphrase = Annotated[SecretStr, Field(max_length=1024)]


class SavedKeyBase(BaseModel):
    name: Text255


class SavedKeyCreate(SavedKeyBase):
    private_key: PrivateKeyText
    # Needed only for an encrypted key; ignored otherwise.
    passphrase: Passphrase | None = None


class SavedKeyUpdate(SavedKeyBase):
    """Partial update. A new private_key is checked with the passphrase sent alongside it
    (none if omitted); a passphrase sent on its own re-checks the stored key."""

    name: Text255 | None = None
    private_key: PrivateKeyText | None = None
    passphrase: Passphrase | None = None

    @model_validator(mode="after")
    def _reject_null_required(self) -> Self:
        for field in ("name", "private_key"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class SavedKeyRead(SavedKeyBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    key_type: str
    fingerprint: str
    public_key: str
    # The key and passphrase are never returned.
    has_passphrase: bool
    server_count: int
    created_at: datetime
    updated_at: datetime
