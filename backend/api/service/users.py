import logging
import secrets
from functools import cache

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import find_user, revoke_tokens
from api.auth.password import hash_password, needs_rehash, verify_password
from api.config import Settings
from api.db.base import utcnow
from api.enums import UserRole
from api.models import AppSettings, User
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


class AccountBlocked(Exception):
    """The password was right, but the account can't sign in. Safe to tell the caller: they
    already proved they know the password."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@cache
def _dummy_hash() -> str:
    return hash_password(secrets.token_urlsafe(16))


async def authenticate(
    session: AsyncSession, email: str, password: str, *, detached: bool = False
) -> User | None:
    """Check credentials and record the login. Returns None for an unknown email or a wrong
    password, without saying which; raises AccountBlocked for a disabled or pending account.

    Detached (a database upgrade is waiting): only reads, so the login isn't recorded.
    """
    user = await find_user(session, User.email == email, detached=detached)
    # Verify against a throwaway hash for unknown emails, so a miss takes as long as a wrong password.
    password_hash = user.password_hash if user is not None else _dummy_hash()
    valid = await run_in_threadpool(verify_password, password_hash, password)
    if user is None or not valid:
        return None
    if not user.is_active:
        raise AccountBlocked("account_disabled", "This account has been disabled")
    if user.is_pending:
        raise AccountBlocked("account_pending", "Your account is waiting for approval")
    if detached:
        return user

    if needs_rehash(user.password_hash):
        user.password_hash = await run_in_threadpool(hash_password, password)
    user.last_login_at = utcnow()
    await session.commit()
    return user


async def signup_open(session: AsyncSession) -> bool:
    settings = await session.get(AppSettings, 1)
    return settings is None or settings.signup_open


async def count_active_admins(session: AsyncSession) -> int:
    """Admins who can sign in. vservx never lets this reach zero."""
    return await session.scalar(
        select(func.count()).select_from(User)
        .where(User.role == UserRole.ADMIN, User.is_active, User.approved_at.is_not(None))
    ) or 0


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
    user.approved_at = utcnow()
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
