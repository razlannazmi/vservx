from enum import StrEnum


class AuthType(StrEnum):
    PASSWORD = "password"
    KEY = "key"


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


class SnapshotKind(StrEnum):
    """What a snapshot records about its instance."""

    FIRST_SEEN = "first_seen"
    RECREATED = "recreated"
    RECREATED_SAME = "recreated_same"
    CHANGED = "changed"
    REMOVED = "removed"


class WatchState(StrEnum):
    """Where vservx stands with watching a server."""

    NOT_TESTED = "not_tested"
    JUMP_ONLY = "jump_only"
    CHECKING = "checking"
    CONNECTED = "connected"
    UNREACHABLE = "unreachable"
    SIGN_IN_FAILED = "sign_in_failed"
    HOST_KEY_CHANGED = "host_key_changed"


class DockerStatus(StrEnum):
    """Whether vservx can run docker on a server, and how."""

    UNKNOWN = "unknown"
    PLAIN = "plain"
    SUDO = "sudo"
    NEEDS_SUDO_PASSWORD = "needs_sudo_password"
    SUDO_PASSWORD_REJECTED = "sudo_password_rejected"
    SUDO_NEEDS_TTY = "sudo_needs_tty"
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
