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


class LaunchType(StrEnum):
    DOCKER = "docker"
    SYSTEMD = "systemd"
    BARE = "bare"


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class SnapshotTrigger(StrEnum):
    DISCOVERY = "discovery"
    PRE_STOP = "pre-stop"
    MANUAL = "manual"
