"""JWT access tokens.

Each token carries the user's token_version; bumping it on the user revokes every token
issued before. The signing key lives in its own file, so deleting it signs everyone out
without touching the stored server secrets.
"""

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import jwt

from api.db.base import utcnow
from api.db.crypto import load_or_create_key

_ALGORITHM = "HS256"

_key: bytes | None = None


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    token_version: int


class InvalidToken(Exception):
    pass


def init_tokens(key_path: Path) -> None:
    global _key
    _key, _ = load_or_create_key(key_path)


def _get_key() -> bytes:
    if _key is None:
        raise RuntimeError("init_tokens() must be called before issuing or checking tokens")
    return _key


def create_access_token(user_id: int, token_version: int, expires_in: timedelta) -> str:
    now = utcnow()
    claims = {"sub": str(user_id), "ver": token_version, "iat": now, "exp": now + expires_in}
    return jwt.encode(claims, _get_key(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    """Check the signature and expiry. The caller still compares token_version with the user's."""
    try:
        claims = jwt.decode(token, _get_key(), algorithms=[_ALGORITHM],
                            options={"require": ["sub", "ver", "iat", "exp"]})
        return TokenClaims(user_id=int(claims["sub"]), token_version=int(claims["ver"]))
    except (jwt.InvalidTokenError, ValueError, TypeError) as exc:
        raise InvalidToken(str(exc)) from exc
