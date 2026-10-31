import logging
import secrets
from functools import cache

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import find_user, revoke_tokens
from api.auth.password import hash_password, needs_rehash, verify_password
from api.config import Settings
from api.db.base import utcnow
from api.enums import UserRole
from api.models import User
from api.schemas import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


def user_from_create(data: UserCreate) -> User:
    fields = data.model_dump(exclude={"password"})
    return User(**fields, password_hash=hash_password(data.password.get_secret_value()))


def apply_user_update(user: User, update: UserUpdate) -> None:
    """Apply a partial update, hashing a new password and revoking tokens when access changes."""
    fields = update.model_dump(exclude_unset=True, exclude={"password"})
    for name, value in fields.items():
        setattr(user, name, value)

    if update.password is not None:
        user.password_hash = hash_password(update.password.get_secret_value())
    # Revoke on deactivation too, so reactivating the account doesn't revive old tokens.
    if update.password is not None or fields.get("is_active") is False:
        revoke_tokens(user)


@cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


async def authenticate(
    session: AsyncSession, email: str, password: str, *, detached: bool = False
) -> User | None:
    """Check credentials and record the login. Returns None on any failure, without saying which.

    Detached (a database upgrade is waiting): only reads, so the login isn't recorded.
    """
    user = await find_user(session, User.email == email, detached=detached)
    # Verify against a throwaway hash for unknown emails, so a miss takes as long as a wrong password.
    password_hash = user.password_hash if user is not None else _dummy_hash()
    valid = await run_in_threadpool(verify_password, password_hash, password)
    if user is None or not valid or not user.is_active:
        return None
    if detached:
        return user

    if needs_rehash(user.password_hash):
        user.password_hash = await run_in_threadpool(hash_password, password)
    user.last_login_at = utcnow()
    await session.commit()
    return user


async def seed_admin(session: AsyncSession, settings: Settings) -> User | None:
    """Create the first admin if no users exist yet. Returns the new user, or None if skipped."""
    if await session.scalar(select(exists().select_from(User))):
        return None

    generated = settings.admin_password is None
    password = secrets.token_urlsafe(16) if generated else settings.admin_password.get_secret_value()
    # Validate through the schema so a bad VSERVX_ADMIN_* value fails startup with a clear error.
    data = UserCreate(name=settings.admin_name, email=settings.admin_email,
                      password=password, role=UserRole.ADMIN)
    user = user_from_create(data)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        # Another process seeded it first.
        await session.rollback()
        return None

    if generated:
        logger.warning(
            "Created admin account %s with generated password: %s  "
            "(shown once; change it after signing in, or set VSERVX_ADMIN_PASSWORD before first run)",
            user.email, password,
        )
    else:
        logger.info("Created admin account %s", user.email)
    return user
