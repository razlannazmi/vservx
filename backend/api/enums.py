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


class DatabaseState(StrEnum):
    """How the database's schema compares with this version of vservx."""

    NEW = "new"
    CURRENT = "current"
    UPGRADE_REQUIRED = "upgrade_required"
    NEWER_THAN_APP = "newer_than_app"


class SnapshotTrigger(StrEnum):
    DISCOVERY = "discovery"
    PRE_STOP = "pre-stop"
    MANUAL = "manual"
