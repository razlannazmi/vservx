from enum import StrEnum


class AuthType(StrEnum):
    PASSWORD = "password"
    KEY = "key"


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
