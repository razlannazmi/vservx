from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, StringConstraints, model_validator

from api.enums import WorkspaceRole
from api.schemas.server import Text255

# Ownership only moves through a hand-over, never through the member routes.
MemberRole = Literal[WorkspaceRole.OPERATOR, WorkspaceRole.VIEWER]

# A movingicons icon's name, such as "flask-conical". Only its shape is checked: the UI owns the
# list, and shows its default for a name it doesn't know.
IconName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=64)]


class WorkspaceCreate(BaseModel):
    name: Text255
    icon: IconName | None = None


class WorkspaceUpdate(BaseModel):
    """Partial update: omitted fields are left unchanged; a null icon goes back to the default."""

    name: Text255 | None = None
    icon: IconName | None = None

    @model_validator(mode="after")
    def _reject_null_name(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class WorkspaceRead(BaseModel):
    id: int
    name: str
    icon: str | None
    # The caller's own role here, so the UI knows which buttons to show.
    role: WorkspaceRole
    member_count: int
    created_at: datetime


class AccountSummary(BaseModel):
    """Enough to recognise an account by: what an owner sees when adding members."""

    id: int
    name: str
    email: str


class MemberRead(BaseModel):
    user_id: int
    name: str
    email: str
    role: WorkspaceRole


class MemberAdd(BaseModel):
    user_id: int
    role: MemberRole


class MemberUpdate(BaseModel):
    role: MemberRole


class OwnerChange(BaseModel):
    user_id: int


class AdminWorkspaceRead(BaseModel):
    id: int
    name: str
    # None only for an ownerless workspace, which the accounts migration creates from a database without accounts.
    owner: AccountSummary | None
    member_count: int
