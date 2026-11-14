"""vLLM run as systemd services, found next to Docker's containers."""

import logging
import time

from sqlalchemy import select

from api.models import Snapshot
from api.watch.docker import DOCKER_MISSING
from tests.helpers import MODEL, SystemdHost, show_block, wait_for, watched_server

USER_BUS = "Failed to connect to bus: No medium found"


def _watch(api, w, sshd, host):
    server_id = watched_server(api, w, sshd(password="ssh-pw", commands=host))
    return server_id, lambda: api.get(f"{w}/servers/{server_id}/watch").json()


def _ready(view):
    return bool(view["instances"]) and all(i["state"] == "ready" for i in view["instances"])


def _vllm(port, name="vllm.service", **fields):
    return show_block(name, f"/opt/venv/bin/vllm serve {MODEL} --port {port}", **fields)


def test_systemd_service_is_watched(watching, client, api, w, sshd, fake_vllm):
    _, get_view = _watch(api, w, sshd, SystemdHost(fake_vllm))
    view = wait_for(get_view, lambda v: v["instances"] and v["instances"][0]["state"] == "ready")
    inst = view["instances"][0]
    assert (inst["source"], inst["name"], inst["model"], inst["version"]) == (
        "systemd", "vllm-llama.service", MODEL, "0.11.0")
    assert view["systemd"] == "available"
    # CUDA_VISIBLE_DEVICES=0 in the unit's Environment=.
    assert inst["gpus"] == ["0"] and [g["instances"] for g in view["gpus"]] == [["vllm-llama.service"], []]


def test_docker_wrapped_unit_is_skipped(watching, client, api, w, sshd, fake_vllm):
    host = SystemdHost(fake_vllm)
    host.show = show_block("vllm-llama.service", f"/usr/bin/docker run --rm vllm/vllm-openai --model {MODEL}")
    _, get_view = _watch(api, w, sshd, host)
    view = wait_for(get_view, lambda v: v["systemd"] == "available" and v["found_at"])
    assert view["instances"] == []


def test_wrapper_unit_counts_only_when_it_runs_vllm(watching, client, api, w, sshd, fake_vllm):
    host = SystemdHost(fake_vllm)
    host.units = "vllm-wrap.service loaded active running x\nvllm-dock.service loaded active running y\n"
    host.files = ""
    host.show = show_block("vllm-wrap.service", "/opt/start.sh") + "\n" + show_block("vllm-dock.service", "/opt/start2.sh")
    host.procs = {
        "/system.slice/vllm-wrap.service":
            f"4100 /bin/sh /opt/start.sh\n4101 python -m vllm.entrypoints.openai.api_server --port {fake_vllm.port}\n",
        "/system.slice/vllm-dock.service": "4200 /bin/sh /opt/start2.sh\n4201 docker run vllm/vllm-openai\n",
    }
    host.compute_apps = "4101, GPU-bbb\n"
    _, get_view = _watch(api, w, sshd, host)
    view = wait_for(get_view, _ready)
    [inst] = view["instances"]
    assert (inst["name"], inst["port"], inst["gpus"]) == ("vllm-wrap.service", fake_vllm.port, ["GPU-bbb"])
    assert [g["instances"] for g in view["gpus"]] == [[], ["vllm-wrap.service"]]


def test_system_and_user_units_with_same_name_are_both_shown(watching, client, api, w, sshd, fake_vllm):
    host = SystemdHost(fake_vllm)
    host.units, host.files = "vllm.service loaded active running x\n", ""
    host.show = _vllm(fake_vllm.port)
    host.user_units = host.units
    host.user_show = _vllm(fake_vllm.port, control_group="/user.slice/user-1000.slice/user@1000.service/vllm.service")
    _, get_view = _watch(api, w, sshd, host)
    view = wait_for(get_view, lambda v: len(v["instances"]) == 2)
    assert {(i["source"], i["name"]) for i in view["instances"]} == {
        ("systemd", "vllm.service"), ("systemd-user", "vllm.service")}


def test_systemctl_failure_does_not_remove_services(watching, client, api, w, sshd, fake_vllm, db):
    host = SystemdHost(fake_vllm)
    _, get_view = _watch(api, w, sshd, host)
    wait_for(get_view, _ready)
    host.error = "Failed to list units: Connection timed out\n"
    view = wait_for(get_view, lambda v: v["systemd"] == "unavailable")
    time.sleep(0.8)  # a few more discoveries

    async def kinds(session):
        return [s.kind.value for s in await session.scalars(select(Snapshot))]
    assert [i["name"] for i in get_view()["instances"]] == ["vllm-llama.service"]
    assert view["systemd_message"] == "Failed to list units: Connection timed out"
    assert db(kinds) == ["first_seen"]


def test_escaped_template_unit_is_watched(watching, client, api, w, sshd, fake_vllm):
    name = "vllm@meta\\x2dllama.service"
    host = SystemdHost(fake_vllm)
    host.units = f"{name} loaded active running vLLM on meta-llama\n"
    host.files = "vllm@.service indirect enabled\n"
    host.show = _vllm(fake_vllm.port, name, control_group=f"/system.slice/system-vllm.slice/{name}")
    _, get_view = _watch(api, w, sshd, host)
    view = wait_for(get_view, _ready)
    assert [i["name"] for i in view["instances"]] == [name]
    # Stopped and unloaded: list-units drops it, and `show` loads it again from its template's file.
    host.units = ""
    host.show = _vllm(fake_vllm.port, name, active="inactive", sub="dead")
    view = wait_for(get_view, lambda v: v["instances"] and v["instances"][0]["state"] == "stopped")
    assert [i["name"] for i in view["instances"]] == [name] and view["removed"] == []
    assert "vllm@.service" not in host.shown


def test_missing_user_bus_is_ignored(watching, client, api, w, sshd, fake_vllm, caplog):
    host = SystemdHost(fake_vllm)
    host.user_error = USER_BUS + "\n"
    with caplog.at_level(logging.INFO, logger="api.watch.server"):
        server_id, get_view = _watch(api, w, sshd, host)
        view = wait_for(get_view, _ready)
        time.sleep(0.8)  # a few more discoveries
    assert (view["systemd"], view["systemd_message"]) == ("available", None)
    assert [i["source"] for i in view["instances"]] == ["systemd"]
    logged = [r.getMessage() for r in caplog.records if "--user" in r.getMessage()]
    assert len(logged) == 1 and str(server_id) in logged[0] and USER_BUS in logged[0]


def test_systemd_only_server_is_not_a_docker_problem(watching, client, api, w, sshd, fake_vllm, workspace):
    _, get_view = _watch(api, w, sshd, SystemdHost(fake_vllm))
    view = wait_for(get_view, _ready)
    assert (view["docker"], view["docker_message"]) == ("unavailable", DOCKER_MISSING)
    [overview] = [o for o in api.get("/api/workspaces/overview").json() if o["workspace_id"] == workspace]
    assert (overview["servers"]["docker_problem"], overview["servers"]["up"]) == (0, 1)


UNIT_TEXT = """# /etc/systemd/system/vllm-llama.service
[Service]
Environment=HF_TOKEN=hf_secret CUDA_VISIBLE_DEVICES=0
ExecStart=/opt/venv/bin/vllm serve meta-llama/Llama-3.1-8B-Instruct --port 8000 --api-key vllm-key
"""
UNIT = "vllm-llama.service"


def _entries(api, w, server_id):
    return api.get(f"{w}/servers/{server_id}/snapshots").json()["entries"]


def test_unit_snapshot_masks_secrets(watching, client, api, w, sshd, fake_vllm):
    host = SystemdHost(fake_vllm)
    host.cat[UNIT] = UNIT_TEXT
    server_id, _ = _watch(api, w, sshd, host)
    [entry] = wait_for(lambda: _entries(api, w, server_id), bool)
    detail = api.get(f"{w}/servers/{server_id}/snapshots/{entry['id']}").json()
    assert detail["kind"] == "first_seen" and detail["source"] == "systemd" and "hf_secret" not in detail["command"]
    assert "vllm-key" not in detail["command"]
    assert "Environment=HF_TOKEN=<HF_TOKEN>" in detail["command"]
    assert "--api-key <VLLM_API_KEY>" in detail["command"]
    assert detail["command"].endswith("sudo systemctl daemon-reload && sudo systemctl enable --now vllm-llama.service")
    assert (detail["image"], detail["image_id"], detail["compose"], detail["env_values_hidden"]) == (None,) * 3 + (False,)


def test_unit_change_writes_changed_snapshot(watching, client, api, w, sshd, fake_vllm):
    host = SystemdHost(fake_vllm)
    host.cat[UNIT] = UNIT_TEXT
    server_id, _ = _watch(api, w, sshd, host)
    wait_for(lambda: _entries(api, w, server_id), bool)
    host.cat[UNIT] = UNIT_TEXT.rstrip() + " --max-model-len 8192\n"
    entries = wait_for(lambda: _entries(api, w, server_id), lambda e: len(e) == 2)
    assert entries[0]["kind"] == "changed"
    assert [d["label"] for d in entries[0]["differences"]] == ["unit file", "unit file"]


def test_new_vllm_version_writes_changed_snapshot(watching, client, api, w, sshd, fake_vllm):
    host = SystemdHost(fake_vllm)
    host.cat[UNIT] = UNIT_TEXT
    server_id, get_view = _watch(api, w, sshd, host)
    wait_for(get_view, _ready)
    entries = wait_for(lambda: _entries(api, w, server_id), bool)
    first = wait_for(lambda: api.get(f"{w}/servers/{server_id}/snapshots/{entries[0]['id']}").json(),
                     lambda d: d["vllm_version"] == "0.11.0")
    fake_vllm.version = "0.12.0"
    host.show = host.show.replace("08:00:00", "09:00:00")  # restarted
    entries = wait_for(lambda: _entries(api, w, server_id), lambda e: len(e) == 2)
    assert entries[0]["kind"] == "changed" and first["id"] == entries[1]["id"]
    assert entries[0]["differences"] == [{"label": "vLLM", "before": "0.11.0", "after": "0.12.0", "note": None}]
