"""Reading SSH private keys that users paste or upload."""

from dataclasses import dataclass

import asyncssh


@dataclass(frozen=True)
class KeyInfo:
    key_type: str
    fingerprint: str
    # One-line OpenSSH public key; safe to show.
    public_key: str
    encrypted: bool


class InvalidKey(ValueError):
    """The key can't be used. str(exc) is a message for the user."""


def _normalize(text: str) -> str:
    # Pasted or uploaded text may carry a BOM, Windows line endings or surrounding blank lines.
    return text.removeprefix("﻿").replace("\r\n", "\n").strip()


def _import(private_key: str, passphrase: str | None) -> tuple[asyncssh.SSHKey, bool]:
    """Import a key, returning it and whether it needed the passphrase."""
    text = _normalize(private_key)
    try:
        return asyncssh.import_private_key(text, None), False
    except asyncssh.KeyImportError as exc:
        # asyncssh: "Passphrase must be specified to import encrypted private keys"
        if "passphrase" not in str(exc).lower():
            raise InvalidKey("Not a valid private key") from None
    if passphrase is None:
        raise InvalidKey("This key is protected by a passphrase; enter it to save the key")
    try:
        return asyncssh.import_private_key(text, passphrase), True
    except (asyncssh.KeyEncryptionError, asyncssh.KeyImportError):
        # PEM formats report a wrong passphrase as an import error ("Unable to decrypt ...").
        raise InvalidKey("Incorrect passphrase") from None


def inspect_private_key(private_key: str, passphrase: str | None = None) -> KeyInfo:
    """Check that the key loads (with the passphrase if it's encrypted) and describe it."""
    key, encrypted = _import(private_key, passphrase)
    return KeyInfo(
        key_type=key.get_algorithm(),
        fingerprint=key.get_fingerprint(),
        public_key=key.export_public_key().decode().strip(),
        encrypted=encrypted,
    )


def load_private_key(private_key: str, passphrase: str | None = None) -> asyncssh.SSHKey:
    return _import(private_key, passphrase)[0]


def fingerprint_of(public_key: str) -> str:
    """SHA256 fingerprint of a one-line OpenSSH public key."""
    return asyncssh.import_public_key(public_key).get_fingerprint()
