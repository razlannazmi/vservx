from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.tokens import InvalidToken, decode_access_token
from api.db.deps import SessionDep
from api.enums import UserRole
from api.models import User
from api.service.database import DatabaseGateDep

_bearer = HTTPBearer(auto_error=False)

# The web app's session: the same token as the bearer header, in an HttpOnly cookie.
SESSION_COOKIE = "vservx_session"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Columns every revision of the users table has. While a database upgrade waits, sign-in reads
# only these, so a migration that adds a column to users can't lock the admin out of running it.
# A migration that drops or renames one of them must update this list.
AUTH_COLUMNS = ("id", "name", "email", "password_hash", "role", "is_active", "token_version",
                "approved_at", "last_login_at", "created_at", "updated_at")


async def find_user(session: AsyncSession, condition: ColumnElement[bool], *, detached: bool) -> User | None:
    """Look up one user. Detached (an upgrade is waiting): read only AUTH_COLUMNS, into a User
    outside the session, so nothing loads or saves columns the older table may lack."""
    if not detached:
        return await session.scalar(select(User).where(condition))
    table = User.__table__
    row = (await session.execute(select(*(table.c[name] for name in AUTH_COLUMNS)).where(condition))).first()
    return None if row is None else User(**row._mapping)


def _unauthorized() -> HTTPException:
    # One response for every failure so callers can't tell which check rejected them.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def set_session_cookie(response: Response, request: Request, token: str, max_age: int) -> None:
    """Keep the token where page scripts can't read it. SameSite=Strict keeps other sites'
    pages from sending it; Secure whenever the request itself came over HTTPS."""
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, path="/", httponly=True, samesite="strict",
                        secure=request.url.scheme == "https")


def clear_session_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict",
                           secure=request.url.scheme == "https")


async def get_current_user(
    request: Request,
    session: SessionDep,
    gate: DatabaseGateDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    # A bearer header (scripts, /docs) wins over the browser's cookie.
    if credentials is not None:
        token = credentials.credentials
    else:
        token = request.cookies.get(SESSION_COOKIE)
        if token is None:
            raise _unauthorized()
        # Another app on the same host is same-site, so SameSite alone doesn't stop it posting
        # with the cookie. A custom header can't be sent cross-origin without a CORS preflight.
        if request.method not in _SAFE_METHODS and request.headers.get("x-vservx") != "1":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing X-Vservx header")
    try:
        claims = decode_access_token(token)
    except InvalidToken:
        raise _unauthorized() from None

    user = await find_user(session, User.id == claims.user_id, detached=not gate.ready)
    # A token_version mismatch means the token was revoked after it was issued.
    if user is None or not user.is_active or user.is_pending or user.token_version != claims.token_version:
        raise _unauthorized()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUserDep) -> User:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def revoke_tokens(user: User) -> None:
    """Invalidate every token issued to this user so far. Takes effect on commit."""
    user.token_version += 1
