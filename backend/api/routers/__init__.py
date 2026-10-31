from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.routers import auth, database, health, servers, ssh_keys
from api.service.database import require_current_database

router = APIRouter(prefix="/api")
# Public: health checks and sign-in.
router.include_router(health.router)
router.include_router(auth.router)
# Signed in, whatever state the database is in, so a waiting upgrade can be seen and run.
router.include_router(database.router, dependencies=[Depends(get_current_user)])

# Everything else requires an up-to-date database (503 otherwise) and a signed-in user;
# add new routers here.
protected = APIRouter(dependencies=[Depends(require_current_database), Depends(get_current_user)])
protected.include_router(servers.router)
protected.include_router(ssh_keys.router)
router.include_router(protected)
