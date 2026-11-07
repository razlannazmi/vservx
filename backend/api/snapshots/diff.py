"""What differs between any two snapshots. The change list uses it on neighbours, and compare on
any pair, so both read the same."""

from collections.abc import Callable
from dataclasses import dataclass

from api.snapshots.command import shm_text
from api.snapshots.config import LaunchConfig
from api.snapshots.secrets import placeholder

KEY_FILE_REPLACED = "can't compare (vservx's key file was replaced)"


@dataclass(frozen=True)
class Point:
    """One snapshot, as far as comparing goes."""

    container_id: str | None
    image_id: str | None
    config: LaunchConfig | None
    key_fingerprint: str | None
    key_id: str | None


@dataclass(frozen=True)
class Difference:
    label: str
    # None on one side means added or removed.
    before: str | None
    after: str | None
    note: str | None = None


def _split_args(args: tuple[str, ...]) -> tuple[list[str], dict[str, str]]:
    """Positional words, and flags with their values, paired as the command pairs them."""
    positional: list[str] = []
    flags: dict[str, list[str]] = {}
    i = 0
    while i < len(args):
        word = args[i]
        if not word.startswith("-"):
            positional.append(word)
            i += 1
            continue
        flag, sep, value = word.partition("=")
        if sep:
            flags.setdefault(flag, []).append(value)
            i += 1
        elif i + 1 < len(args) and not args[i + 1].startswith("-"):
            flags.setdefault(word, []).append(args[i + 1])
            i += 2
        else:
            flags.setdefault(word, []).append("")
            i += 1
    return positional, {flag: " ".join(values) for flag, values in flags.items()}


def _env(entries: tuple[str, ...]) -> dict[str, str | None]:
    """Name to value; None for a secret, whose value is never seen."""
    env: dict[str, str | None] = {}
    for entry in entries:
        key, sep, value = entry.partition("=")
        env[key] = value if sep else None
    return env


def _joined(values: tuple[str, ...]) -> str | None:
    return ", ".join(values) or None


# The other options, labelled by their docker run flag, in the command's order.
_OPTIONS: tuple[tuple[str, Callable[[LaunchConfig], str | None]], ...] = (
    ("--gpus", lambda c: c.gpus),
    ("--runtime", lambda c: c.runtime),
    ("--ipc", lambda c: c.ipc),
    ("--pid", lambda c: c.pid),
    ("--shm-size", lambda c: shm_text(c.shm_size) if c.shm_size else None),
    ("--network", lambda c: c.network),
    ("-p", lambda c: _joined(c.ports)),
    ("-v", lambda c: _joined(c.volumes)),
    ("--device", lambda c: _joined(c.devices)),
    ("--ulimit", lambda c: _joined(c.ulimits)),
    ("--cap-add", lambda c: _joined(c.cap_add)),
    ("--cap-drop", lambda c: _joined(c.cap_drop)),
    ("--privileged", lambda c: "on" if c.privileged else None),
    ("--user", lambda c: c.user),
    ("--workdir", lambda c: c.workdir),
    ("--restart", lambda c: c.restart),
    ("compose", lambda c: " ".join(c.compose) if c.compose else None),
)


def _config_differences(old: Point, new: Point) -> list[Difference]:
    a, b = old.config, new.config
    if a is None or b is None:
        return []
    found: list[Difference] = []
    if a.image != b.image:
        found.append(Difference("image", a.image, b.image))
    elif old.image_id and new.image_id and old.image_id != new.image_id:
        found.append(Difference("image", a.image, b.image, "re-pulled"))
    if a.entrypoint != b.entrypoint:
        found.append(Difference("entrypoint", " ".join(a.entrypoint) if a.entrypoint is not None else None,
                                " ".join(b.entrypoint) if b.entrypoint is not None else None))
    old_positional, old_flags = _split_args(a.args)
    new_positional, new_flags = _split_args(b.args)
    if old_positional != new_positional:
        found.append(Difference("arguments", " ".join(old_positional) or None, " ".join(new_positional) or None))
    for flag, value in new_flags.items():
        if flag not in old_flags:
            found.append(Difference(flag, None, value))
        elif old_flags[flag] != value:
            found.append(Difference(flag, old_flags[flag], value))
    found.extend(Difference(flag, value, None) for flag, value in old_flags.items() if flag not in new_flags)
    old_env, new_env = _env(a.env), _env(b.env)
    for name in sorted(old_env.keys() | new_env.keys()):
        label = f"-e {name}"
        if name not in old_env:
            found.append(Difference(label, None, new_env[name] if new_env[name] is not None else placeholder(name)))
        elif name not in new_env:
            found.append(Difference(label, old_env[name] if old_env[name] is not None else placeholder(name), None))
        elif None not in (old_env[name], new_env[name]) and old_env[name] != new_env[name]:
            # A secret's value is never seen, so only adding or removing one shows.
            found.append(Difference(label, old_env[name], new_env[name]))
    for label, read in _OPTIONS:
        before, after = read(a), read(b)
        if before != after:
            found.append(Difference(label, before, after))
    return found


def differences(old: Point, new: Point) -> list[Difference]:
    found = _config_differences(old, new)
    if old.key_id and new.key_id and old.key_id != new.key_id:
        found.append(Difference("API key", None, None, KEY_FILE_REPLACED))
    elif old.key_fingerprint != new.key_fingerprint:
        found.append(Difference("API key", old.key_fingerprint, new.key_fingerprint))
    if old.container_id != new.container_id:
        found.append(Difference("container", (old.container_id or "")[:12] or None, (new.container_id or "")[:12] or None))
    return found


def same_launch(old: Point, new: Point) -> bool:
    """The same launch config and API key. A fingerprint made under another key file can't be
    compared, so it never counts as a change."""
    rekeyed = bool(old.key_id and new.key_id and old.key_id != new.key_id)
    return old.config == new.config and (old.key_fingerprint == new.key_fingerprint or rekeyed)
