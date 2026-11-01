import asyncio

from api.enums import DockerStatus
from api.watch.docker import probe_docker
from api.watch.shell import CommandResult
from tests.watch_samples import PS_OUTPUT


class FakeRunner:
    def __init__(self, replies: dict[str, CommandResult]) -> None:
        self.replies, self.calls = replies, []

    async def run(self, command: str, stdin: str | None = None) -> CommandResult:
        self.calls.append((command, stdin))
        return next(reply for prefix, reply in self.replies.items() if command.startswith(prefix))


DENIED = CommandResult(1, "", "permission denied while trying to connect to the Docker daemon socket")
NEEDS = CommandResult(1, "", "sudo: a password is required")
OK = CommandResult(0, PS_OUTPUT, "")


def test_docker_access_falls_back_to_sudo() -> None:
    runner = FakeRunner({"docker ": DENIED, "sudo -n ": NEEDS, "sudo -S ": OK})
    access, ps = asyncio.run(probe_docker(runner, "pw"))
    assert (access.status, ps.stdout) == (DockerStatus.SUDO, PS_OUTPUT)
    command, stdin = runner.calls[-1]
    assert stdin == "pw\n" and "pw" not in command
    assert asyncio.run(probe_docker(FakeRunner({"docker ": OK}), "pw"))[0].status is DockerStatus.PLAIN
    no_password = FakeRunner({"docker ": DENIED, "sudo -n ": NEEDS})
    assert asyncio.run(probe_docker(no_password, None))[0].status is DockerStatus.NEEDS_SUDO_PASSWORD
    rejected = CommandResult(1, "", "Sorry, try again.\nsudo: 1 incorrect password attempt")
    runner = FakeRunner({"docker ": DENIED, "sudo -n ": NEEDS, "sudo -S ": rejected})
    assert asyncio.run(probe_docker(runner, "bad"))[0].status is DockerStatus.SUDO_PASSWORD_REJECTED
    missing = FakeRunner({"docker ": CommandResult(127, "", "bash: docker: command not found")})
    assert asyncio.run(probe_docker(missing, None))[0].message == "Docker isn't installed on this server."
