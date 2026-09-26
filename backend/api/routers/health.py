from fastapi import APIRouter

from api.schemas.health import HealthResponse
from api.version import __version__

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)
