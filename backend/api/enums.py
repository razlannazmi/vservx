from enum import StrEnum


class AuthType(StrEnum):
    PASSWORD = "password"
    KEY = "key"


class ServerKind(StrEnum):
    """How vservx reaches a server."""

    SSH = "ssh"
    THIS_MACHINE = "this_machine"


class InstanceSource(StrEnum):
    """What runs an instance."""

    DOCKER = "docker"
    SYSTEMD = "systemd"
    SYSTEMD_USER = "systemd-user"


class ConnectionFailure(StrEnum):
    """Why an SSH hop failed."""

    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    HOST_KEY_CHANGED = "host_key_changed"
    CREDENTIALS_UNREADABLE = "credentials_unreadable"
    ERROR = "error"


class UserRole(StrEnum):
    """App-wide role. What someone may do inside a workspace is their WorkspaceRole there."""

    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceRole(StrEnum):
    """A member's role inside one workspace, lowest first."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    OWNER = "owner"

    def at_least(self, other: "WorkspaceRole") -> bool:
        order = list(WorkspaceRole)
        return order.index(self) >= order.index(other)


class DatabaseState(StrEnum):
    """How the database's schema compares with this version of vservx."""

    NEW = "new"
    CURRENT = "current"
    UPGRADE_REQUIRED = "upgrade_required"
    NEWER_THAN_APP = "newer_than_app"


class StoreState(StrEnum):
    """Whether the history store can keep and serve history right now."""

    # No store is set: history lives in memory only.
    OFF = "off"
    OK = "ok"
    UNREACHABLE = "unreachable"
    UPGRADE_REQUIRED = "upgrade_required"
    NEWER_THAN_APP = "newer_than_app"


class SnapshotKind(StrEnum):
    """What a snapshot records about its instance."""

    FIRST_SEEN = "first_seen"
    RECREATED = "recreated"
    RECREATED_SAME = "recreated_same"
    CHANGED = "changed"
    REMOVED = "removed"


class ThresholdMetric(StrEnum):
    """A usage reading an instance's warning and critical thresholds apply to, named after its
    UsagePoint field. Higher is worse for each."""

    WAITING = "waiting"
    KV_CACHE_PERCENT = "kv_cache_percent"
    TTFT_SECONDS = "ttft_seconds"


class WatchState(StrEnum):
    """Where vservx stands with watching a server."""

    NOT_TESTED = "not_tested"
    JUMP_ONLY = "jump_only"
    CHECKING = "checking"
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    SIGN_IN_FAILED = "sign_in_failed"
    HOST_KEY_CHANGED = "host_key_changed"
    NEEDS_ADMIN_OWNER = "needs_admin_owner"


class DockerStatus(StrEnum):
    """Whether vservx can run docker on a server, and how."""

    UNKNOWN = "unknown"
    PLAIN = "plain"
    SUDO = "sudo"
    NEEDS_SUDO_PASSWORD = "needs_sudo_password"
    SUDO_PASSWORD_REJECTED = "sudo_password_rejected"
    SUDO_NEEDS_TTY = "sudo_needs_tty"
    UNAVAILABLE = "unavailable"


class SystemdStatus(StrEnum):
    """Whether vservx can read systemd services on a server."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    # No systemd on the machine; not an error.
    MISSING = "missing"
    # Systemd is there but could not be read; a message says why.
    UNAVAILABLE = "unavailable"


class InstanceState(StrEnum):
    """What a watched instance is doing, from its container and its health check."""

    READY = "ready"
    STARTING = "starting"
    NOT_RESPONDING = "not_responding"
    RESTARTING = "restarting"
    CRASHED = "crashed"
    STOPPED = "stopped"
    PAUSED = "paused"
    # vservx has no way to reach the instance's port.
    UNREACHABLE = "unreachable"
