from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth.tokens import InvalidToken, decode_access_token
from api.db.deps import SessionDep
from api.models import User

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    # One response for every failure so callers can't tell which check rejected them.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidToken:
        raise _unauthorized() from None

    user = await session.get(User, claims.user_id)
    # A token_version mismatch means the token was revoked after it was issued.
    if user is None or not user.is_active or user.token_version != claims.token_version:
        raise _unauthorized()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def revoke_tokens(user: User) -> None:
    """Invalidate every token issued to this user so far. Takes effect on commit."""
    user.token_version += 1
