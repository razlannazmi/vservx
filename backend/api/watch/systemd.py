"""Reading systemd services: the commands to run, and parsing what they print.

Pure functions, no I/O. Secret rules come from api/snapshots/secrets.py: the awk programs that run
on the server are generated from the same constants as is_secret_env, so the two can't drift.
Command lines and unit text are never logged.
"""

import os
import re
import shlex
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from api.snapshots.secrets import SECRET_NAME_PARTS, SECRET_NAME_SUFFIXES, is_secret_env, mask_args, placeholder

# Env a unit keeps with its value. VLLM_API_KEY is held in memory only.
UNIT_KEPT_ENV = ("VLLM_API_KEY", "CUDA_VISIBLE_DEVICES")

SHOW_PROPERTIES = (
    "Id", "LoadState", "ActiveState", "SubState", "Result", "ExecMainStatus", "ExecMainStartTimestamp",
    "ExecMainExitTimestamp", "NRestarts", "ExecStart", "Environment", "ControlGroup",
)

# POSIX awk only (no gensub, FPAT): servers may run mawk or busybox awk. No single quotes, so the
# program can sit in a single-quoted shell word.
_AWK_SECRET_TEST = " || ".join(
    [f'index(u, "{part}") > 0' for part in SECRET_NAME_PARTS]
    + [f'substr(u, length(u) - {len(s) - 1}) == "{s}"' for s in SECRET_NAME_SUFFIXES]
)
_AWK_KEPT_TEST = " || ".join(f'name == "{n}"' for n in UNIT_KEPT_ENV)

# rewrite(rest, mode) goes through the words of an Environment= value, split the way systemd does:
# a word ends at whitespace outside quotes, either quote character opens a quote anywhere in the word,
# and a backslash escapes the next character. A quote still open at the end of the value is no quote:
# the word is taken again, ending at its next whitespace. mode "show": a secret name not kept goes out
# as its name only, and only a leading double quote opens a quote (systemctl show quotes whole
# entries). mode "cat": a secret assignment becomes NAME=<NAME>. Every other word goes out as it came in.
_AWK_FUNCTIONS = r"""
function secret(name,   u) { u = toupper(name); return (""" + _AWK_SECRET_TEST + r""") }
function kept(name) { return (""" + _AWK_KEPT_TEST + r""") }
function continued(l,   n, k) {
  n = length(l); k = 0
  while (n - k > 0 && substr(l, n - k, 1) == "\\") k++
  return k % 2
}
function rewrite(rest, mode,   out, n, i, s, c, qc, raw, plain, name, p) {
  n = length(rest); i = 1; out = ""
  while (i <= n) {
    c = substr(rest, i, 1)
    if (c == " " || c == "\t") { out = out c; i++; continue }
    s = i; raw = ""; plain = ""; qc = ""
    while (i <= n) {
      c = substr(rest, i, 1)
      if (qc == "" && (c == " " || c == "\t")) break
      raw = raw c; i++
      if (c == "\\" && i <= n) { c = substr(rest, i, 1); raw = raw c; i++; plain = plain c }
      else if (qc == "" && (c == "\"" || (mode == "cat" && c == "\047")) && (mode == "cat" || length(raw) == 1)) qc = c
      else if (c == qc) qc = ""
      else plain = plain c
    }
    if (qc != "") {
      i = s; raw = ""
      while (i <= n && substr(rest, i, 1) != " " && substr(rest, i, 1) != "\t") { raw = raw substr(rest, i, 1); i++ }
      plain = raw
    }
    p = index(plain, "=")
    name = p ? substr(plain, 1, p - 1) : plain
    if (mode == "show" && secret(name) && !kept(name)) out = out name
    else if (mode == "cat" && p && secret(name)) out = out name "=<" name ">"
    else out = out raw
  }
  return out
}
function credential(rest,   p, id) {
  p = index(rest, ":")
  if (p < 2) return rest
  id = substr(rest, 1, p - 1)
  return id ":<" id ">"
}
"""

# Only known `show` lines go out: a raw newline inside a quoted Environment value would otherwise
# let the tail of a multi-line secret through.
_AWK_KNOWN_LINE = " || ".join(f'index($0, "{key}=") == 1' for key in SHOW_PROPERTIES)

ENV_FILTER_AWK = _AWK_FUNCTIONS + r"""
{
  if (index($0, "Environment=") == 1) print "Environment=" rewrite(substr($0, 13), "show")
  else if ($0 ~ /^[ \t]*$/ || (""" + _AWK_KNOWN_LINE + r""")) print
}
"""

# Directive names may be followed by whitespace before "=", and a commented-out line is masked too.
# A trailing backslash joins the next line, so a continued directive is masked as one line; comment
# lines inside a continuation are masked and printed on their own, and the joining goes on after them.
UNIT_MASK_AWK = _AWK_FUNCTIONS + r"""
function comment(l) { return (l ~ /^[ \t]*[#;]/) }
function mask1(l,   n) {
  if (match(l, /^[ \t]*([#;][ \t]*)*Environment[ \t]*=[ \t]*/)) { n = RLENGTH; return substr(l, 1, n) rewrite(substr(l, n + 1), "cat") }
  if (match(l, /^[ \t]*([#;][ \t]*)*SetCredential(Encrypted)?[ \t]*=[ \t]*/)) { n = RLENGTH; return substr(l, 1, n) credential(substr(l, n + 1)) }
  return l
}
{
  line = $0
  if (!comment(line) && line ~ /^[ \t]*(Environment|SetCredential|SetCredentialEncrypted)[ \t]*=/)
    while (continued(line) && (getline nxt) > 0) {
      if (comment(nxt)) print mask1(nxt)
      else line = substr(line, 1, length(line) - 1) " " nxt
    }
  print mask1(line)
}
"""


def _systemctl(user: bool) -> str:
    return "systemctl --user" if user else "systemctl"


def list_command(user: bool) -> str:
    sc = _systemctl(user)
    return (f"{sc} list-units --type=service --all --plain --no-legend --no-pager"
            f" && {sc} list-unit-files --type=service --plain --no-legend --no-pager")


def parse_unit_names(stdout: str) -> list[str]:
    names: dict[str, None] = {}
    for line in stdout.splitlines():
        words = line.lstrip().lstrip("●*").split()
        if words and words[0].endswith(".service") and not words[0].endswith("@.service"):
            names[words[0]] = None
    return list(names)


def show_command(units: list[str], user: bool) -> str:
    # TZ=UTC makes the timestamps parse as "%a %Y-%m-%d %H:%M:%S UTC".
    return (f"TZ=UTC LC_ALL=C {_systemctl(user)} show --no-pager -p {','.join(SHOW_PROPERTIES)} -- "
            f"{' '.join(shlex.quote(u) for u in units)} | LC_ALL=C awk {shlex.quote(ENV_FILTER_AWK)}")


@dataclass(frozen=True)
class UnitInfo:
    name: str
    load_state: str
    active_state: str
    sub_state: str
    result: str
    exit_status: int | None
    started_at: datetime | None
    finished_at: datetime | None
    restarts: int
    argv: list[str] = field(repr=False)
    env: dict[str, str] = field(repr=False)  # kept names only
    env_entries: tuple[str, ...] = field(repr=False)
    control_group: str


_ARGV = re.compile(r"argv\[\]=(.*?) ; (?=\w+=)")


def _words(text: str, show: bool = False) -> Iterator[tuple[str, str | None]]:
    """(raw, plain) for each word of an Environment= value, split the way systemd does: a word ends
    at whitespace outside quotes, either quote character opens a quote anywhere in it, and a
    backslash escapes the next character. A quote still open at the end is no quote: the word is
    taken again, ending at its next whitespace. With `show` (systemctl show quotes whole entries),
    only a leading double quote opens a quote. Runs of whitespace come back as (raw, None)."""
    i, n = 0, len(text)
    while i < n:
        start = i
        if text[i] in " \t":
            while i < n and text[i] in " \t":
                i += 1
            yield text[start:i], None
            continue
        quote, plain = "", []
        while i < n:
            c = text[i]
            if not quote and c in " \t":
                break
            i += 1
            if c == "\\" and i < n:
                plain.append(text[i])
                i += 1
            elif not quote and (c == '"' and i - start == 1 if show else c in "\"'"):
                quote = c
            elif c == quote:
                quote = ""
            else:
                plain.append(c)
        if quote:
            i = start
            while i < n and text[i] not in " \t":
                i += 1
            plain = [text[start:i]]
        yield text[start:i], "".join(plain)


def _none_if_blank(value: str) -> str | None:
    return None if value in ("", "n/a") else value


def _timestamp(value: str) -> datetime | None:
    if _none_if_blank(value) is None:
        return None
    try:
        return datetime.strptime(value, "%a %Y-%m-%d %H:%M:%S UTC").replace(tzinfo=UTC)
    except ValueError:
        return None


def _int(value: str) -> int | None:
    text = _none_if_blank(value)
    return int(text) if text is not None and text.lstrip("-").isdigit() else None


def _argv(exec_start: str) -> list[str]:
    match = _ARGV.search(exec_start)
    if not match:
        return []
    try:
        return shlex.split(match[1])
    except ValueError:
        return match[1].split()


def _env_entries(value: str) -> tuple[str, ...]:
    return tuple(plain for _, plain in _words(value, show=True) if plain is not None)


def _unit(props: dict[str, str]) -> UnitInfo:
    entries = _env_entries(props.get("Environment", ""))
    pairs = (entry.partition("=") for entry in entries if "=" in entry)
    return UnitInfo(
        name=props.get("Id", ""),
        load_state=props.get("LoadState", ""),
        active_state=props.get("ActiveState", ""),
        sub_state=props.get("SubState", ""),
        result=props.get("Result", ""),
        exit_status=_int(props.get("ExecMainStatus", "")),
        started_at=_timestamp(props.get("ExecMainStartTimestamp", "")),
        finished_at=_timestamp(props.get("ExecMainExitTimestamp", "")),
        restarts=_int(props.get("NRestarts", "")) or 0,
        argv=_argv(props.get("ExecStart", "")),
        env={name: val for name, _, val in pairs if name in UNIT_KEPT_ENV},
        env_entries=entries,
        control_group=props.get("ControlGroup", ""),
    )


def parse_show(stdout: str) -> list[UnitInfo]:
    units = []
    for block in re.split(r"\n\s*\n", stdout.strip()):
        props = {}
        for line in block.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                props.setdefault(key, value)  # the first of a repeated property wins
        if props:
            units.append(_unit(props))
    return units


def docker_wrapped(argv: list[str]) -> bool:
    return bool(argv) and os.path.basename(argv[0]) in ("docker", "podman", "docker-compose")


def systemd_state(info: UnitInfo) -> tuple[str, int | None, bool]:
    """Docker's status words for a unit, so api/watch/states.py needs no changes."""
    active, sub = info.active_state, info.sub_state
    oom = info.result == "oom-kill"
    if active == "active":
        return ("running", None, False) if sub == "running" else ("exited", 0, False)
    if active == "reloading":
        return ("running", None, False)
    if active == "activating":
        return ("restarting" if sub == "auto-restart" else "running", None, False)
    if active == "deactivating" or (active == "inactive" and info.result == "success"):
        return ("exited", 0, False)
    return ("dead", info.exit_status, oom)


def cgroup_command(control_group: str) -> str | None:
    """Prints "PID argv..." for each process in the unit's cgroup, v2 first and then v1."""
    if not control_group.startswith("/") or ".." in control_group:
        return None
    return (
        f"cg={shlex.quote(control_group)}; f=\"/sys/fs/cgroup$cg/cgroup.procs\"; "
        "[ -r \"$f\" ] || f=\"/sys/fs/cgroup/systemd$cg/cgroup.procs\"; "
        "for p in $(cat \"$f\" 2>/dev/null); do "
        "case $p in *[!0-9]*) continue;; esac; "
        "printf '%s ' \"$p\"; tr '\\0' ' ' < \"/proc/$p/cmdline\" 2>/dev/null; echo; done"
    )


def parse_processes(stdout: str) -> list[tuple[int, list[str]]]:
    processes = []
    for line in stdout.splitlines():
        words = line.split()
        if words and words[0].isdigit():
            processes.append((int(words[0]), words[1:]))
    return processes


def cat_command(unit: str, user: bool) -> str:
    return f"{_systemctl(user)} cat --no-pager -- {shlex.quote(unit)} | LC_ALL=C awk {shlex.quote(UNIT_MASK_AWK)}"


_COMMENT = re.compile(r"^\s*[#;]")
_CONTINUABLE = re.compile(r"^\s*(?:Environment|SetCredential|SetCredentialEncrypted|Exec\w*)\s*=")
# Each also matches a commented-out line: its "#" or ";" is part of the prefix.
_ENV_LINE = re.compile(r"^(\s*(?:[#;]\s*)*Environment\s*=\s*)(.*)$")
_CREDENTIAL_LINE = re.compile(r"^(\s*(?:[#;]\s*)*SetCredential(?:Encrypted)?\s*=\s*)([^:]+):.*$")
_EXEC_LINE = re.compile(r"^(\s*(?:[#;]\s*)*Exec\w*\s*=\s*)([-@+!:]*)(.*)$")
_EXEC_WORD = re.compile(r"""(?:"(?:\\.|[^"\\])*"|'[^']*'|\\.|[^\s"'\\])+|["'\\]""")


def _mask_env_value(value: str) -> str:
    out = []
    for raw, plain in _words(value):
        name, sep, _ = (plain or "").partition("=")
        out.append(f"{name}={placeholder(name)}" if sep and is_secret_env(name) else raw)
    return "".join(out)


def _mask_exec(prefix: str, flags: str, command: str) -> str:
    raw = _EXEC_WORD.findall(command)
    words = []
    for token in raw:
        try:
            parsed = shlex.split(token)
        except ValueError:
            parsed = []
        words.append(parsed[0] if len(parsed) == 1 else token)
    masked = mask_args(words)
    out = [
        token if new == word else (shlex.quote(new) if any(c.isspace() for c in new) else new)
        for token, word, new in zip(raw, words, masked)
    ]
    return prefix + flags + " ".join(out)


def _mask_line(line: str) -> str:
    if m := _ENV_LINE.match(line):
        return m[1] + _mask_env_value(m[2])
    if m := _CREDENTIAL_LINE.match(line):
        return f"{m[1]}{m[2]}:{placeholder(m[2])}"
    if m := _EXEC_LINE.match(line):
        return _mask_exec(m[1], m[2], m[3])
    return line


def mask_unit_text(text: str) -> str:
    """The guard run on arrival, in case the server-side awk didn't run. Masks Environment= and
    SetCredential*= the same way, and the secret flags on Exec*= lines, commented out or not. A
    odd number of trailing backslashes joins the next line into one logical line; a comment line inside the
    continuation is masked and kept on its own, and the joining goes on after it. Every other
    line is left byte-identical."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not _COMMENT.match(line) and _CONTINUABLE.match(line):
            while (len(line) - len(line.rstrip("\\"))) % 2 == 1 and i < len(lines):
                nxt = lines[i]
                i += 1
                if _COMMENT.match(nxt):
                    out.append(_mask_line(nxt))
                else:
                    line = line[:-1] + " " + nxt
        out.append(_mask_line(line))
    return "\n".join(out)
