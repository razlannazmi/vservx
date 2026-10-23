import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest

from api.enums import ConnectionFailure
from api.ssh.connect import ChainReport, Hop, run_connection_test
from tests.helpers import make_key, public_line
from tests.sshd import FakeSSHD

Sshd = Callable[..., FakeSSHD]


def _hop(server: FakeSSHD, name: str = "gpu-7", **creds) -> Hop:
    return Hop(name=name, host=server.host, port=server.port, username="ubuntu",
               password=creds.get("password"), client_key=creds.get("client_key"),
               host_key=creds.get("host_key"))


def _run(hops: list[Hop], timeout: float = 5.0) -> ChainReport:
    return asyncio.run(run_connection_test(hops, timeout))


def test_changed_host_key_refused_before_login(sshd: Sshd) -> None:
    server = sshd(password="pw")
    _, other = make_key()

    [hop] = _run([_hop(server, password="pw", host_key=public_line(other))]).hops

    assert hop.reason is ConnectionFailure.HOST_KEY_CHANGED
    assert hop.fingerprint == server.host_key.get_fingerprint()
    assert server.auth_attempts == []


def test_pinned_key_type_no_longer_offered_is_a_changed_key(sshd: Sshd) -> None:
    server = sshd(password="pw")  # offers only ed25519
    _, rsa = make_key(algorithm="ssh-rsa")

    [hop] = _run([_hop(server, password="pw", host_key=public_line(rsa))]).hops

    assert (hop.reason, hop.fingerprint) == (ConnectionFailure.HOST_KEY_CHANGED, server.host_key.get_fingerprint())
    assert server.auth_attempts == []


def test_unreachable(sshd: Sshd, closed_port: int) -> None:
    hop = Hop("gpu-7", "127.0.0.1", closed_port, "ubuntu", "pw", None, None)
    bastion = _hop(sshd(password="pw"), "bastion-1", password="pw")

    assert _run([hop]).hops[0].reason is ConnectionFailure.UNREACHABLE
    # Same answer when it's the jump host that can't get through.
    assert _run([bastion, hop]).hops[1].reason is ConnectionFailure.UNREACHABLE


def test_timeout(silent_port: int) -> None:
    hop = Hop("gpu-7", "127.0.0.1", silent_port, "ubuntu", "pw", None, None)

    assert _run([hop], timeout=0.5).hops[0].reason is ConnectionFailure.TIMEOUT


def test_two_jump_hosts(sshd: Sshd) -> None:
    servers = [sshd(password="pw", hostname=f"h{i}") for i in range(3)]

    report = _run([_hop(s, f"h{i}", password="pw") for i, s in enumerate(servers)])

    assert (report.ok, report.hostname) == (True, "h2")
    assert [h.name for h in report.hops] == ["h0", "h1", "h2"]


def test_failure_names_failing_hop(sshd: Sshd) -> None:
    bastion, gpu = sshd(password="j"), sshd(password="t")

    report = _run([_hop(bastion, "bastion-1", password="j"), _hop(gpu, "gpu-7", password="wrong")])

    assert [h.ok for h in report.hops] == [True, False]
    assert report.hops[1].reason is ConnectionFailure.AUTH_FAILED


def test_ignores_local_ssh_config(sshd: Sshd, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "config").write_text("Host *\n  ProxyCommand vservx-no-such-command\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)

    assert _run([_hop(sshd(password="pw"), password="pw")]).ok
