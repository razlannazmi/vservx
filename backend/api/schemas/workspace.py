from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from api.enums import WorkspaceRole
from api.schemas.server import Text255

# Ownership only moves through a hand-over, never through the member routes.
MemberRole = Literal[WorkspaceRole.OPERATOR, WorkspaceRole.VIEWER]


class WorkspaceCreate(BaseModel):
    name: Text255


class WorkspaceUpdate(BaseModel):
    name: Text255


class WorkspaceRead(BaseModel):
    id: int
    name: str
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
    # None only for a workspace moved in by the upgrade from a database with no accounts.
    owner: AccountSummary | None
    member_count: int
