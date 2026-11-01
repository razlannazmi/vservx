from fastapi import APIRouter

from api.db.deps import SessionDep
from api.enums import DatabaseState
from api.schemas.health import HealthResponse
from api.service.database import DatabaseGateDep
from api.service.users import signup_open
from api.version import __version__

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(gate: DatabaseGateDep, session: SessionDep) -> HealthResponse:
    status = await gate.refresh()
    # The setting lives in the database, so it's only read once the schema is current.
    is_open = status.state is DatabaseState.CURRENT and await signup_open(session)
    return HealthResponse(status="ok", version=__version__, database=status.state, signup_open=is_open)
