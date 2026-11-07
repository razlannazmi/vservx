"""The `docker run` command rebuilt from a launch config, one option per line so a line diff of two
commands reads cleanly. Placeholders are written unquoted, so pasting one unfilled fails in the
shell instead of running with a wrong value."""

import re
import shlex

from api.snapshots.config import LaunchConfig
from api.snapshots.secrets import SECRET_FLAGS, placeholder

COVERS = (
    "Covers image, entrypoint and arguments, env, ports, network, IPC, PID, shm size, GPUs, runtime, volumes, "
    "restart policy, ulimits, devices, privileged, capabilities, user and working directory. "
    "Anything else isn't included."
)
ENV_HIDDEN_LINE = "This server's Docker is too old for vservx to separate secrets, so no env values are shown."

# Only the placeholders masking writes into arguments; any other <WORD> is quoted like normal text.
_ARG_PLACEHOLDERS = re.compile("(" + "|".join(re.escape(placeholder(name)) for name in SECRET_FLAGS.values()) + ")")


def _quote(word: str) -> str:
    """shlex.quote, except that a placeholder anywhere in the word stays bare."""
    parts = _ARG_PLACEHOLDERS.split(word)
    return "".join(part if i % 2 else (shlex.quote(part) if part else "") for i, part in enumerate(parts)) or "''"


def _env(entry: str) -> str:
    key, sep, _ = entry.partition("=")
    return f"-e {shlex.quote(key)}={placeholder(key)}" if not sep else f"-e {shlex.quote(entry)}"


def shm_text(size: int) -> str:
    for unit, scale in (("g", 1024**3), ("m", 1024**2)):
        if size % scale == 0:
            return f"{size // scale}{unit}"
    return str(size)


def pair_words(words: list[str]) -> list[str]:
    """A word starting with "-" shares its line with the next word when that one doesn't start
    with "-"; every other word sits on its own line."""
    lines = []
    i = 0
    while i < len(words):
        word = words[i]
        if word.startswith("-") and i + 1 < len(words) and not words[i + 1].startswith("-"):
            lines.append(f"{_quote(word)} {_quote(words[i + 1])}")
            i += 2
        else:
            lines.append(_quote(word))
            i += 1
    return lines


def docker_run(name: str, config: LaunchConfig) -> str:
    items: list[str] = []
    if config.gpus:
        items.append(f"--gpus {shlex.quote(config.gpus)}")
    for flag, value in (("--runtime", config.runtime), ("--ipc", config.ipc), ("--pid", config.pid)):
        if value:
            items.append(f"{flag} {shlex.quote(value)}")
    if config.shm_size:
        items.append(f"--shm-size {shm_text(config.shm_size)}")
    if config.network:
        items.append(f"--network {shlex.quote(config.network)}")
    for flag, values in (("-p", config.ports), ("-v", config.volumes), ("--device", config.devices),
                         ("--ulimit", config.ulimits), ("--cap-add", config.cap_add), ("--cap-drop", config.cap_drop)):
        items.extend(f"{flag} {shlex.quote(value)}" for value in values)
    if config.privileged:
        items.append("--privileged")
    if config.user:
        items.append(f"--user {shlex.quote(config.user)}")
    if config.workdir:
        items.append(f"--workdir {shlex.quote(config.workdir)}")
    items.extend(_env(entry) for entry in config.env)
    if config.restart:
        items.append(f"--restart {shlex.quote(config.restart)}")
    rest: list[str] = []
    if config.entrypoint is not None:
        first, *rest = config.entrypoint or ("",)
        items.append(f"--entrypoint {_quote(first)}")
    items.append(shlex.quote(config.image))
    items.extend(pair_words([*rest, *config.args]))
    return " \\\n".join([f"docker run -d --name {shlex.quote(name)}", *(f"  {item}" for item in items)])


def compose_line(config: LaunchConfig) -> str | None:
    if config.compose is None:
        return None
    project, files = config.compose
    return (f"Started by docker compose (project {project}) from {files}. "
            "Running it again with compose is safer than this command.")
