import logging
import secrets

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import revoke_tokens
from api.auth.password import hash_password
from api.config import Settings
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
