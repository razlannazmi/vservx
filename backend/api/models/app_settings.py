from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class AppSettings(Base):
    """Settings app admins change at runtime. One row, id 1, created by the migration."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Whether anyone may ask for an account (an app admin still approves each one).
    signup_open: Mapped[bool] = mapped_column(default=True)
