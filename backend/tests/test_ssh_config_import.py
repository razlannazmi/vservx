from fastapi.testclient import TestClient

from api.ssh.config_import import parse_ssh_config

CONFIG = """\
# lab
Host bastion
    HostName 203.0.113.10
    User ops
    IdentityFile ~/.ssh/lab_ed25519

Host gpu-7 gpu-8
    HostName %h.lab.internal
    ProxyJump bastion
    IdentityFile C:\\Users\\me\\keys\\aws-gpu.pem

Host *
    User ubuntu
    Port 2222
"""


def test_concrete_hosts_become_entries() -> None:
    hosts, warnings = parse_ssh_config(CONFIG)

    assert [h.name for h in hosts] == ["bastion", "gpu-7", "gpu-8"]
    bastion, gpu7, gpu8 = hosts
    assert (bastion.host, bastion.port, bastion.user, bastion.identity_files) == ("203.0.113.10", 2222, "ops", ["lab_ed25519"])
    assert (gpu7.host, gpu7.user, gpu7.proxy_jump, gpu7.identity_files) == ("gpu-7.lab.internal", "ubuntu", ["bastion"], ["aws-gpu.pem"])
    assert gpu8.host == "gpu-8.lab.internal"
    assert warnings == [] and all(h.warnings == [] for h in hosts)


def test_multi_hop_proxy_jump() -> None:
    [_, _, target], _ = parse_ssh_config(
        "Host a\n User u\nHost b\n User u\nHost t\n User u\n ProxyJump a,ops@b:2222\n")

    assert target.proxy_jump == ["a", "b"]


def test_import_preview_saves_nothing(api: TestClient) -> None:
    response = api.post("/api/servers/import-ssh-config", json={"config": CONFIG})

    assert response.status_code == 200
    assert [h["name"] for h in response.json()["hosts"]] == ["bastion", "gpu-7", "gpu-8"]
    assert api.get("/api/servers").json() == []
