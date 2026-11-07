import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from api.auth.limits import KeyCheckLimits, SignInLimits
from api.auth.tokens import init_tokens
from api.config import get_settings
from api.db.crypto import init_crypto
from api.db.engine import create_engine, create_sessionmaker
from api.enums import DatabaseState
from api.routers import router as api_router
from api.service.database import DatabaseGate, DatabaseNotReady
from api.service.users import AccountBlocked, seed_admin
from api.version import __version__
from api.watch.watcher import Watcher

logger = logging.getLogger(__name__)

# On every response. No page of vservx is meant to be shown inside another site's frame.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
# Only on the web app's own files, since /docs loads Swagger UI from a CDN. The built app loads
# everything from vservx itself; inline styles stay allowed because Svelte and bits-ui set style
# attributes.
_APP_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)


async def _warn_if_secrets_unreadable(engine: AsyncEngine) -> None:
    """A new key with secrets already stored means the old key file was lost."""
    async with engine.connect() as conn:
        count = (await conn.execute(text(
            "SELECT (SELECT count(*) FROM servers WHERE password IS NOT NULL)"
            "     + (SELECT count(*) FROM ssh_keys)"
        ))).scalar_one()
    if count:
        logger.warning(
            "Generated a new encryption key, but %d stored credential(s) were encrypted with a "
            "previous key. Restore the old secret.key or re-enter them.",
            count,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_created = init_crypto(settings.secret_key_path)
    init_tokens(settings.jwt_key_path)

    engine = create_engine(settings.db_path)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.watcher = Watcher(app.state.sessionmaker, settings)

    async def on_database_ready() -> None:
        # Startup work that uses the database. Held back while an upgrade waits.
        if key_created:
            await _warn_if_secrets_unreadable(engine)
        async with app.state.sessionmaker() as session:
            await seed_admin(session, settings)
        await app.state.watcher.start()

    app.state.database = DatabaseGate(settings.db_path, on_database_ready)
    await app.state.database.start()
    try:
        yield
    finally:
        # Closes every server's SSH connection.
        await app.state.watcher.stop()
        await engine.dispose()


async def _integrity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # e.g. "UNIQUE constraint failed: servers.name"
    assert isinstance(exc, IntegrityError)
    return JSONResponse(status_code=409, content={"detail": str(exc.orig)})


async def _database_not_ready_handler(request: Request, exc: Exception) -> JSONResponse:
    # "code" lets the UI tell this apart from other 503s and show the upgrade notice.
    assert isinstance(exc, DatabaseNotReady)
    if exc.state is DatabaseState.NEWER_THAN_APP:
        content = {"detail": "Database is newer than this vservx", "code": "database_newer_than_app"}
    else:
        content = {"detail": "Database upgrade required", "code": "database_upgrade_required"}
    return JSONResponse(status_code=503, content=content)


async def _account_blocked_handler(request: Request, exc: Exception) -> JSONResponse:
    # "code" lets the sign-in page tell waiting-for-approval apart from disabled.
    assert isinstance(exc, AccountBlocked)
    return JSONResponse(status_code=403, content={"detail": exc.message, "code": exc.code})


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # FastAPI's default 422 echoes the rejected value as "input", which can be a password or private key.
    assert isinstance(exc, RequestValidationError)
    errors = [{k: v for k, v in error.items() if k != "input"} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="vservx", version=__version__, lifespan=lifespan)
    app.state.sign_in_limits = SignInLimits()
    app.state.key_check_limits = KeyCheckLimits()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AccountBlocked, _account_blocked_handler)
    app.add_exception_handler(DatabaseNotReady, _database_not_ready_handler)
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)

    @app.middleware("http")
    async def reload_watcher(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Any change inside a workspace (servers, keys, tests, host keys, the workspace itself)
        # brings server watching in step at once, rather than at its next minute.
        response = await call_next(request)
        if (request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/workspaces/")
                and response.status_code < 400 and hasattr(request.app.state, "watcher")):
            request.app.state.watcher.reload()
        return response

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    app.include_router(api_router)

    if (settings.ui_dir / "index.html").is_file():
        _serve_app_files(app, settings.ui_dir)
    else:
        # No built web app yet (npm run build in ui/): say where the API is instead.
        @app.get("/", include_in_schema=False)
        async def root() -> dict[str, str]:
            return {
                "name": "vservx",
                "version": __version__,
                "docs": "/docs",
                "health": "/api/health",
            }

    return app


def _serve_app_files(app: FastAPI, ui_dir: Path) -> None:
    """Serve the built web app. Registered after the API, so API routes match first."""
    root = ui_dir.resolve()
    index = root / "index.html"
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def app_files(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        # Files directly in the build folder (favicon.svg); resolve() so "..\" can't climb out.
        file = (root / path).resolve()
        if path and file.parent == root and file.is_file():
            return FileResponse(file, headers={"Content-Security-Policy": _APP_CSP})
        # Every other path is a page of the app, so links into it work on refresh.
        return FileResponse(index, headers={"Cache-Control": "no-cache", "Content-Security-Policy": _APP_CSP})


app = create_app()


if __name__ == "__main__":
    # Development only: reloads on every code change. Run `vservx serve` in production.
    settings = get_settings()
    uvicorn.run("api.main:app", host=settings.host, port=settings.port, reload=True)
