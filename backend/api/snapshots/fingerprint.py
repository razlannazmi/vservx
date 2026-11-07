"""The API key fingerprint: 8 hex characters of an HMAC of the key, keyed from vservx's key file,
so it's stable across restarts and useless without the key file. Each fingerprint is kept with a
short ID of the HMAC key it was made with, so a replaced key file is told apart from a changed key."""

import hmac
from hashlib import sha256

from api.db.crypto import current_key

_LABEL = b"vservx api-key fingerprint v1"
_LENGTH = 8


def _hmac_key() -> bytes:
    return hmac.new(current_key(), _LABEL, sha256).digest()


def fingerprint(api_key: str) -> tuple[str, str]:
    """The fingerprint and the ID of the HMAC key it was made with."""
    key = _hmac_key()
    return hmac.new(key, api_key.encode(), sha256).hexdigest()[:_LENGTH], sha256(key).hexdigest()[:_LENGTH]


def check_key(candidate: str, stored: str, key_id: str) -> bool | None:
    """Whether a pasted key matches a stored fingerprint, compared in constant time. Surrounding
    whitespace is ignored. None when the fingerprint was made under another key file."""
    made, current_id = fingerprint(candidate.strip())
    if not hmac.compare_digest(key_id, current_id):
        return None
    return hmac.compare_digest(made, stored)
