from fastapi import APIRouter

from api.schemas.health import HealthResponse
from api.service.database import DatabaseGateDep
from api.version import __version__

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(gate: DatabaseGateDep) -> HealthResponse:
    status = await gate.refresh()
    return HealthResponse(status="ok", version=__version__, database=status.state)
