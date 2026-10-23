from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.routers import auth, health, servers, ssh_keys

router = APIRouter(prefix="/api")
# Public: health checks and sign-in.
router.include_router(health.router)
router.include_router(auth.router)

# Everything else requires a signed-in user; add new routers here.
protected = APIRouter(dependencies=[Depends(get_current_user)])
protected.include_router(servers.router)
protected.include_router(ssh_keys.router)
router.include_router(protected)
