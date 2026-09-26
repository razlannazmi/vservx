"""Fernet encryption for secrets stored in the database."""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def load_or_create_key(path: Path) -> tuple[bytes, bool]:
    """Read the key file, generating it with 0600 permissions on first run.

    Returns the key and whether it was newly created.
    """
    if path.exists():
        return path.read_bytes().strip(), False

    key = Fernet.generate_key()
    # O_EXCL so a concurrent start can't overwrite a key another process just wrote.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key, True


def init_crypto(key_path: Path) -> bool:
    """Load the encryption key. Returns True if a new key was generated."""
    global _fernet
    key, created = load_or_create_key(key_path)
    _fernet = Fernet(key)
    return created


def _get_fernet() -> Fernet:
    if _fernet is None:
        raise RuntimeError("init_crypto() must be called before using encrypted columns")
    return _fernet


class EncryptedString(TypeDecorator[str]):
    """A string column that is Fernet-encrypted at rest and plaintext in Python.

    A value that can't be decrypted (the key file was replaced) reads as None, so the
    credential shows as missing and can be re-entered instead of failing the whole query.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return _get_fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            logger.warning(
                "A stored secret could not be decrypted; the key file may have changed. "
                "Re-enter the affected server credentials."
            )
            return None
