from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from api.enums import UserRole
from api.schemas.user import Email, Password, Text255


class SignupRequest(BaseModel):
    name: Text255
    email: Email
    password: Password


class AccountRead(BaseModel):
    """An account as app admins see it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: UserRole
    is_active: bool
    # None while the sign-up waits for approval.
    approved_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class AccountUpdate(BaseModel):
    """What an app admin can change about an account. Partial: omitted fields are left unchanged.
    A new password or disabling signs the person out everywhere."""

    role: UserRole | None = None
    is_active: bool | None = None
    password: Password | None = None

    @model_validator(mode="after")
    def _reject_null(self) -> Self:
        for field in ("role", "is_active", "password"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ProfileUpdate(BaseModel):
    name: Text255


class PasswordChange(BaseModel):
    current_password: SecretStr
    new_password: Password


class AppSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    signup_open: bool


class AppSettingsUpdate(BaseModel):
    signup_open: bool
