"""Which env vars and vLLM flags hold secrets, and how their values are replaced by placeholders.

These constants also generate the `docker inspect` env filter (api/watch/docker.py), so the rule
applied on the server and the one applied on arrival can't drift apart.
"""

import re
from collections.abc import Sequence

# An env name is secret when, upper-cased, it contains one of these or ends in one of the suffixes.
SECRET_NAME_PARTS: tuple[str, ...] = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "API_KEY", "ACCESS_KEY", "PRIVATE_KEY", "CREDENTIAL",
)
SECRET_NAME_SUFFIXES: tuple[str, ...] = ("_KEY",)

# vLLM flags whose value is a secret, and the placeholder name each value becomes. An explicit list,
# since many ordinary flags contain "token" (--tokenizer, --max-num-batched-tokens).
SECRET_FLAGS: dict[str, str] = {"--api-key": "VLLM_API_KEY", "--hf-token": "HF_TOKEN"}

# A secret flag inside one shell-string argument (sh -c "vllm serve … --api-key xyz").
_FLAG_IN_STRING = re.compile(r"(?<!\S)(--api-key|--hf-token)(=|\s+)('[^']*'|\"[^\"]*\"|\S+)")


def is_secret_env(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in SECRET_NAME_PARTS) or upper.endswith(SECRET_NAME_SUFFIXES)


def placeholder(name: str) -> str:
    """Written unquoted in the command, so pasting it unfilled fails in the shell."""
    return f"<{name}>"


def _mask_string(word: str) -> str:
    return _FLAG_IN_STRING.sub(lambda m: m[1] + m[2] + placeholder(SECRET_FLAGS[m[1]]), word)


def mask_args(args: Sequence[str]) -> list[str]:
    """The arguments with every secret flag's value replaced by its placeholder. A secret flag
    with no following value is left alone."""
    masked: list[str] = []
    mask_next: str | None = None
    for word in args:
        if mask_next is not None:
            masked.append(placeholder(mask_next))
            mask_next = None
            continue
        flag, sep, _ = word.partition("=")
        if word in SECRET_FLAGS:
            mask_next = SECRET_FLAGS[word]
            masked.append(word)
        elif sep and flag in SECRET_FLAGS:
            masked.append(f"{flag}={placeholder(SECRET_FLAGS[flag])}")
        elif any(c.isspace() for c in word):
            masked.append(_mask_string(word))
        else:
            masked.append(word)
    return masked
