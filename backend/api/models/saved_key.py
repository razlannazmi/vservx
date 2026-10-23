from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, utcnow
from api.db.crypto import EncryptedString


class SavedKey(Base):
    """A private key saved once and picked for any number of servers."""

    __tablename__ = "ssh_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    # Stored as uploaded. Reads as None if it can't be decrypted (the key file changed).
    private_key: Mapped[str | None] = mapped_column(EncryptedString, nullable=False)
    # Stored only when the key is encrypted.
    passphrase: Mapped[str | None] = mapped_column(EncryptedString)
    # Derived from the key when it's saved; safe to show.
    key_type: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(128))
    public_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    @property
    def has_passphrase(self) -> bool:
        return self.passphrase is not None
