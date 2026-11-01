from typing import Annotated

from fastapi import APIRouter, Query

from api.db.deps import SessionDep
from api.schemas import AccountSummary
from api.service.workspaces import search_accounts

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[AccountSummary])
async def find_accounts(
    q: Annotated[str, Query(min_length=1, max_length=255)], session: SessionDep
) -> list[AccountSummary]:
    """Accounts that can be added to a workspace, searched by name or email."""
    return await search_accounts(session, q)
