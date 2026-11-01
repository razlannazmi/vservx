from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.db.base import utcnow
from api.db.deps import SessionDep
from api.enums import UserRole
from api.models import AppSettings, User, Workspace
from api.schemas import AdminWorkspaceRead, OwnerChange, UserUpdate
from api.schemas.account import AccountRead, AccountUpdate, AppSettingsRead, AppSettingsUpdate
from api.service.users import apply_user_update, count_active_admins
from api.service.workspaces import admin_workspace_read, change_owner, list_all_workspaces

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def _account_or_404(session: AsyncSession, account_id: int) -> User:
    user = await session.get(User, account_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return user


async def _app_settings(session: AsyncSession) -> AppSettings:
    # The migration creates the row; this only covers a database where it went missing.
    settings = await session.get(AppSettings, 1)
    if settings is None:
        settings = AppSettings(id=1, signup_open=True)
        session.add(settings)
    return settings


@router.get("/accounts", response_model=list[AccountRead])
async def list_accounts(session: SessionDep) -> Sequence[User]:
    """Every account, sign-ups waiting for approval first."""
    return (await session.scalars(
        select(User).order_by(case((User.approved_at.is_(None), 0), else_=1), User.name, User.id)
    )).all()


@router.post("/accounts/{account_id}/approve", response_model=AccountRead)
async def approve_account(account_id: int, session: SessionDep) -> User:
    user = await _account_or_404(session, account_id)
    if user.is_pending:
        user.approved_at = utcnow()
        await session.commit()
    return user


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reject_account(account_id: int, session: SessionDep) -> None:
    """Reject a sign-up. Accounts that were ever approved are disabled instead, so history stays attributed."""
    user = await _account_or_404(session, account_id)
    if not user.is_pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only a pending account can be rejected")
    await session.delete(user)
    await session.commit()


@router.patch("/accounts/{account_id}", response_model=AccountRead)
async def update_account(account_id: int, data: AccountUpdate, session: SessionDep) -> User:
    user = await _account_or_404(session, account_id)
    if data.role is UserRole.ADMIN and user.is_pending:
        # Only admins sign in while an upgrade waits, and that path can't see approval.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approve the account first")
    loses_admin = (data.role is not None and data.role is not UserRole.ADMIN) or data.is_active is False
    counts_as_admin = user.role is UserRole.ADMIN and user.is_active and not user.is_pending
    if loses_admin and counts_as_admin and await count_active_admins(session) <= 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="vservx needs at least one active admin")
    apply_user_update(user, UserUpdate(**data.model_dump(exclude_unset=True)))
    await session.commit()
    return user


@router.get("/settings", response_model=AppSettingsRead)
async def get_app_settings(session: SessionDep) -> AppSettings:
    return await _app_settings(session)


@router.patch("/settings", response_model=AppSettingsRead)
async def update_app_settings(data: AppSettingsUpdate, session: SessionDep) -> AppSettings:
    settings = await _app_settings(session)
    settings.signup_open = data.signup_open
    await session.commit()
    return settings


@router.get("/workspaces", response_model=list[AdminWorkspaceRead])
async def list_workspaces(session: SessionDep) -> list[AdminWorkspaceRead]:
    return await list_all_workspaces(session)


@router.post("/workspaces/{workspace_id}/owner", response_model=AdminWorkspaceRead)
async def give_workspace_new_owner(workspace_id: int, data: OwnerChange, session: SessionDep) -> AdminWorkspaceRead:
    """Make any approved account the owner, joining it if needed; the old owner stays on as an operator."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    try:
        await change_owner(session, workspace, data.user_id, must_be_member=False)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    return await admin_workspace_read(session, workspace)
