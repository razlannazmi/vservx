from collections.abc import Iterable

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.enums import WorkspaceRole
from api.models import SavedKey, Server, User, Workspace, WorkspaceMember
from api.schemas import AccountSummary, AdminWorkspaceRead, MemberRead, WorkspaceRead

# Most accounts one search returns; the owner narrows the search rather than scrolling.
SEARCH_LIMIT = 20


async def create_workspace(session: AsyncSession, owner: User, name: str) -> Workspace:
    workspace = Workspace(name=name)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    await session.commit()
    return workspace


async def _member_counts(session: AsyncSession, workspace_ids: Iterable[int]) -> dict[int, int]:
    rows = await session.execute(
        select(WorkspaceMember.workspace_id, func.count())
        .where(WorkspaceMember.workspace_id.in_(list(workspace_ids)))
        .group_by(WorkspaceMember.workspace_id)
    )
    return {workspace_id: count for workspace_id, count in rows}


def _read(workspace: Workspace, role: WorkspaceRole, member_count: int) -> WorkspaceRead:
    return WorkspaceRead(id=workspace.id, name=workspace.name, role=role, member_count=member_count,
                         created_at=workspace.created_at)


async def workspace_read(session: AsyncSession, workspace: Workspace, role: WorkspaceRole) -> WorkspaceRead:
    counts = await _member_counts(session, [workspace.id])
    return _read(workspace, role, counts.get(workspace.id, 0))


async def list_workspaces_for(session: AsyncSession, user: User) -> list[WorkspaceRead]:
    """The workspaces the user belongs to, with their role in each, by name."""
    rows = (await session.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.name, Workspace.id)
    )).all()
    counts = await _member_counts(session, [workspace.id for workspace, _ in rows])
    return [_read(workspace, role, counts.get(workspace.id, 0)) for workspace, role in rows]


def _summary(user: User) -> AccountSummary:
    return AccountSummary(id=user.id, name=user.name, email=user.email)


def _can_join(user: User | None) -> bool:
    return user is not None and user.is_active and not user.is_pending


async def account_that_can_join(session: AsyncSession, user_id: int) -> User:
    """The account to add to a workspace. Raises ValueError for one that can't sign in."""
    user = await session.get(User, user_id)
    if not _can_join(user):
        raise ValueError(f"Account {user_id} does not exist")
    return user


async def search_accounts(session: AsyncSession, query: str) -> list[AccountSummary]:
    """Accounts that can be added to a workspace whose name or email contains query, by name."""
    users = await session.scalars(
        select(User)
        .where(User.is_active, User.approved_at.is_not(None),
               or_(User.name.icontains(query, autoescape=True),
                                   User.email.icontains(query, autoescape=True)))
        .order_by(User.name, User.id)
        .limit(SEARCH_LIMIT)
    )
    return [_summary(user) for user in users]


async def list_members(session: AsyncSession, workspace_id: int) -> list[MemberRead]:
    """Everyone in the workspace, owner first, then by name."""
    rows = await session.execute(
        select(WorkspaceMember.role, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(case((WorkspaceMember.role == WorkspaceRole.OWNER, 0), else_=1), User.name, User.id)
    )
    return [MemberRead(user_id=user.id, name=user.name, email=user.email, role=role) for role, user in rows]


async def member_read(session: AsyncSession, member: WorkspaceMember) -> MemberRead:
    user = await session.get(User, member.user_id)
    assert user is not None
    return MemberRead(user_id=user.id, name=user.name, email=user.email, role=member.role)


async def change_owner(session: AsyncSession, workspace: Workspace, user_id: int, *, must_be_member: bool) -> None:
    """Hand the workspace to user_id; the old owner stays on as an operator. Raises ValueError,
    changing nothing, if the account can't take it. Commits."""
    target = await session.get(WorkspaceMember, (workspace.id, user_id))
    if target is None:
        if must_be_member:
            raise ValueError("Not a member of this workspace")
        await account_that_can_join(session, user_id)
    elif target.role is WorkspaceRole.OWNER:
        return

    # Demote first and flush, so the one-owner index never sees two owners.
    await session.execute(
        update(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.role == WorkspaceRole.OWNER)
        .values(role=WorkspaceRole.OPERATOR)
    )
    if target is None:
        session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user_id, role=WorkspaceRole.OWNER))
    else:
        target.role = WorkspaceRole.OWNER
    await session.commit()


async def delete_workspace(session: AsyncSession, workspace: Workspace) -> None:
    """Delete the workspace and everything in it, in one transaction. Commits.

    Jump links and saved keys are RESTRICT foreign keys, so the links are cut and the servers
    deleted before the keys. Instances and snapshots go with their servers (CASCADE), action
    history stays with its server cleared (SET NULL), and members go with the workspace.
    """
    in_workspace = Server.workspace_id == workspace.id
    await session.execute(update(Server).where(in_workspace).values(jump_server_id=None),
                          execution_options={"synchronize_session": False})
    await session.execute(delete(Server).where(in_workspace), execution_options={"synchronize_session": False})
    await session.execute(delete(SavedKey).where(SavedKey.workspace_id == workspace.id),
                          execution_options={"synchronize_session": False})
    await session.delete(workspace)
    await session.commit()


async def _admin_read(session: AsyncSession, workspaces: list[Workspace]) -> list[AdminWorkspaceRead]:
    ids = [workspace.id for workspace in workspaces]
    counts = await _member_counts(session, ids)
    owners = {
        workspace_id: _summary(user)
        for workspace_id, user in await session.execute(
            select(WorkspaceMember.workspace_id, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id.in_(ids), WorkspaceMember.role == WorkspaceRole.OWNER)
        )
    }
    return [AdminWorkspaceRead(id=workspace.id, name=workspace.name, owner=owners.get(workspace.id),
                               member_count=counts.get(workspace.id, 0))
            for workspace in workspaces]


async def list_all_workspaces(session: AsyncSession) -> list[AdminWorkspaceRead]:
    """Every workspace, for app admins: who owns it and how many are in it, never what's inside."""
    workspaces = list(await session.scalars(select(Workspace).order_by(Workspace.name, Workspace.id)))
    return await _admin_read(session, workspaces)


async def admin_workspace_read(session: AsyncSession, workspace: Workspace) -> AdminWorkspaceRead:
    [read] = await _admin_read(session, [workspace])
    return read
