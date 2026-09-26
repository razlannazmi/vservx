"""Argon2id password hashing for user accounts.

Hashing is deliberately slow (~50ms of CPU). From an async endpoint, call these through
fastapi.concurrency.run_in_threadpool so they don't block the event loop.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    # The salt and parameters are embedded in the returned string.
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash used weaker parameters than the current defaults; rehash after a successful login."""
    return _hasher.check_needs_rehash(password_hash)
