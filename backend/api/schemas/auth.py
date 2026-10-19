from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

# Normalized like stored emails, but not format-checked: a typo gets the same 401 as a wrong password.
LoginEmail = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=255)]


class LoginRequest(BaseModel):
    email: LoginEmail
    # Capped so an oversized body can't make the server hash megabytes.
    password: Annotated[SecretStr, Field(max_length=128)]


class TokenResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    # Seconds until the token expires.
    expires_in: int
