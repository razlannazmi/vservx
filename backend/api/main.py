import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from api.config import get_settings
from api.db.crypto import init_crypto
from api.db.engine import create_engine, create_schema, create_sessionmaker
from api.routers import router as api_router
from api.version import __version__

logger = logging.getLogger(__name__)


async def _warn_if_secrets_unreadable(engine: AsyncEngine) -> None:
    """A new key with secrets already stored means the old key file was lost."""
    async with engine.connect() as conn:
        count = (await conn.execute(text(
            "SELECT count(*) FROM servers WHERE password IS NOT NULL OR key_passphrase IS NOT NULL"
        ))).scalar_one()
    if count:
        logger.warning(
            "Generated a new encryption key, but %d server(s) have stored secrets that were "
            "encrypted with a previous key. Restore the old secret.key or re-enter their credentials.",
            count,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_created = init_crypto(settings.secret_key_path)

    engine = create_engine(settings.db_path)
    await create_schema(engine)
    if key_created:
        await _warn_if_secrets_unreadable(engine)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    # Startup: SSH pool, metrics poller go here.
    try:
        yield
    finally:
        # Shutdown: close SSH connections, stop pollers.
        await engine.dispose()


async def _integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # e.g. "UNIQUE constraint failed: servers.name"
    assert isinstance(exc, IntegrityError)
    return JSONResponse(status_code=409, content={"detail": str(exc.orig)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="vservx", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("api.main:app", host=settings.host, port=settings.port, reload=True)
