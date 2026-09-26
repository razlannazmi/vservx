from fastapi import APIRouter

from api.routers import health

router = APIRouter(prefix="/api")
router.include_router(health.router)
