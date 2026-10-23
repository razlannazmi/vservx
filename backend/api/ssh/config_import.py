"""Reading an uploaded OpenSSH client config into proposed servers.

Only the text is parsed; nothing on the filesystem is read. Options resolve the way ssh does
it: every Host block matching an alias contributes, in file order, and the first value for
a keyword wins (IdentityFile accumulates instead).
"""

import re
import shlex
from dataclasses import dataclass, field

# "Keyword value" or "Keyword=value", with optional spaces around the "=".
_LINE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)\s*(?:=\s*|\s+)(.*)$")


@dataclass(frozen=True)
class ImportedHost:
    name: str
    host: str
    port: int
    user: str | None
    # File names only: the browser matches them to the key files the user uploads.
    identity_files: list[str]
    # Aliases of the jump hosts, outermost first.
    proxy_jump: list[str]
    warnings: list[str]


@dataclass
class _Block:
    patterns: list[str]
    options: list[tuple[str, list[str]]] = field(default_factory=list)

    def applies_to(self, alias: str) -> bool:
        alias = alias.lower()
        if any(_matches(p[1:], alias) for p in self.patterns if p.startswith("!")):
            return False
        return any(_matches(p, alias) for p in self.patterns if not p.startswith("!"))


def _matches(pattern: str, alias: str) -> bool:
    regex = re.escape(pattern.lower()).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, alias) is not None


def _is_concrete(pattern: str) -> bool:
    return not (set(pattern) & {"*", "?"} or pattern.startswith("!"))


def _split(value: str) -> list[str]:
    """Split a value into arguments: double quotes group, '#' starts a comment, and
    backslashes are kept (Windows paths)."""
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    lexer.escape = ""
    try:
        return list(lexer)
    except ValueError:  # unbalanced quote
        return value.split()


def _file_name(path: str) -> str:
    return re.split(r"[\\/]", path)[-1]


def _jump_alias(hop: str) -> str:
    """Strip ssh://, user@ and :port from one ProxyJump hop."""
    hop = hop.removeprefix("ssh://").rsplit("@", 1)[-1]
    if hop.startswith("["):  # [IPv6]:port
        return hop[1:].split("]", 1)[0]
    return hop.split(":", 1)[0]


def _parse_blocks(text: str) -> tuple[list[_Block], list[str], list[str]]:
    """Return the blocks (the first holds options set before any Host line), the concrete
    aliases in file order, and file-level warnings."""
    blocks = [_Block(["*"])]
    aliases: list[str] = []
    warnings: list[str] = []
    in_match = False
    for number, raw in enumerate(text.removeprefix("﻿").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _LINE.match(line)
        if parsed is None:
            warnings.append(f"Line {number}: couldn't read {line!r}")
            continue
        keyword, args = parsed.group(1).lower(), _split(parsed.group(2))
        if keyword == "host":
            in_match = False
            blocks.append(_Block(args))
            aliases += [p for p in args if _is_concrete(p) and p not in aliases]
        elif keyword == "match":
            in_match = True
            warnings.append(f"Line {number}: Match blocks aren't supported; their options were skipped")
        elif in_match:
            continue
        elif keyword == "include":
            warnings.append(f"Line {number}: Include isn't supported; upload the included file's hosts separately")
        elif args:
            blocks[-1].options.append((keyword, args))
    return blocks, aliases, warnings


def _resolve(alias: str, blocks: list[_Block]) -> ImportedHost:
    first: dict[str, list[str]] = {}
    identity_files: list[str] = []
    for block in blocks:
        if not block.applies_to(alias):
            continue
        for keyword, args in block.options:
            if keyword == "identityfile":
                name = _file_name(args[0])
                if name not in identity_files:
                    identity_files.append(name)
            else:
                first.setdefault(keyword, args)

    warnings: list[str] = []
    host = first.get("hostname", ["%h"])[0].replace("%h", alias)
    port = 22
    if "port" in first:
        value = first["port"][0]
        if value.isdigit() and 1 <= int(value) <= 65535:
            port = int(value)
        else:
            warnings.append(f"Port {value!r} isn't a valid port; using 22")
    user = first["user"][0] if "user" in first else None
    if user is None:
        warnings.append("No User is set; enter the username before saving")
    proxy_jump: list[str] = []
    jump = first.get("proxyjump", ["none"])[0]
    if jump.lower() != "none":
        proxy_jump = [_jump_alias(hop) for hop in jump.split(",") if hop]
    if first.get("proxycommand", ["none"])[0].lower() != "none":
        warnings.append("ProxyCommand isn't supported; add the jump host as a saved server instead")
    return ImportedHost(alias, host, port, user, identity_files, proxy_jump, warnings)


def parse_ssh_config(text: str) -> tuple[list[ImportedHost], list[str]]:
    """Proposed servers, one per concrete Host alias in file order, plus file-level warnings."""
    blocks, aliases, warnings = _parse_blocks(text)
    return [_resolve(alias, blocks) for alias in aliases], warnings
