from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)

from api.enums import UserRole

Text255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Email = Annotated[EmailStr, AfterValidator(str.lower)]
Password = Annotated[SecretStr, Field(min_length=8, max_length=128)]


class UserBase(BaseModel):
    """Fields shared by every user schema. The password lives only in Create/Update."""

    name: Text255
    email: Email
    role: UserRole = UserRole.VIEWER
    is_active: bool = True


class UserCreate(UserBase):
    password: Password


class UserUpdate(UserBase):
    """Partial update: omitted fields are left unchanged.

    Apply with api.service.users.apply_user_update, which hashes the password and revokes tokens.
    """

    name: Text255 | None = None
    email: Email | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: Password | None = None

    @model_validator(mode="after")
    def _reject_null_required(self) -> Self:
        for field in ("name", "email", "role", "is_active", "password"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
