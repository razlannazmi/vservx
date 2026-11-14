import shutil
import subprocess
from datetime import UTC, datetime

import pytest

from api.watch.systemd import (
    ENV_FILTER_AWK,
    UNIT_MASK_AWK,
    UnitInfo,
    cgroup_command,
    docker_wrapped,
    mask_unit_text,
    parse_show,
    parse_unit_names,
    systemd_state,
)

SHOW = """Id=vllm-llama.service
LoadState=loaded
ActiveState=active
SubState=running
Result=success
ExecMainStatus=0
ExecMainStartTimestamp=Thu 2026-11-12 08:00:00 UTC
ExecMainExitTimestamp=
NRestarts=2
ExecStart={ path=/opt/venv/bin/vllm ; argv[]=/opt/venv/bin/vllm serve m --port 8001 --api-key k ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }
Environment=VLLM_API_KEY=k HF_TOKEN CUDA_VISIBLE_DEVICES=0,1 PYTHONPATH=/x
ControlGroup=/system.slice/vllm-llama.service
"""


def test_parse_show():
    [info] = parse_show(SHOW)
    assert info.argv[:3] == ["/opt/venv/bin/vllm", "serve", "m"]
    assert info.env == {"VLLM_API_KEY": "k", "CUDA_VISIBLE_DEVICES": "0,1"}
    assert info.started_at == datetime(2026, 11, 12, 8, 0, tzinfo=UTC) and info.restarts == 2
    assert "VLLM_API_KEY" not in repr(info)  # the key stays in memory only
    [first] = parse_show(SHOW + "ExecStart={ path=/other ; argv[]=/other/vllm ; ignore_errors=no }\n")
    assert first.argv[0] == "/opt/venv/bin/vllm"


@pytest.mark.parametrize("active,sub,result,expected", [
    ("active", "running", "success", ("running", None, False)),
    ("activating", "auto-restart", "exit-code", ("restarting", None, False)),
    ("failed", "failed", "oom-kill", ("dead", 137, True)),
    ("inactive", "dead", "success", ("exited", 0, False)),
])
def test_systemd_state(active, sub, result, expected):
    info = UnitInfo(
        name="x.service", load_state="loaded", active_state=active, sub_state=sub, result=result,
        exit_status=137, started_at=None, finished_at=None, restarts=0,
        argv=[], env={}, env_entries=(), control_group="/x",
    )
    assert systemd_state(info) == expected


def test_parse_unit_names():
    out = "● vllm-a.service loaded failed failed x\nvllm@.service enabled enabled\nvllm@m.service loaded active running x\nfoo.socket x\n"
    assert parse_unit_names(out) == ["vllm-a.service", "vllm@m.service"]


def test_docker_wrapped():
    assert docker_wrapped(["/usr/bin/docker", "run", "x"]) and not docker_wrapped(["/opt/vllm", "serve"])


UNIT_TEXT = (
    "[Service]\nEnvironment=HF_TOKEN=hf_x PYTHONPATH=/x\nSetCredential=tok:abc\n"
    "Environment=PYTHONPATH=/x \\\n  HF_TOKEN=hf_cont\n"
    "Environment = HF_TOKEN=hf_spaced\n"
    "Environment='PASSWORD=pw_one two' X=1\n"
    "#Environment=HF_TOKEN=hf_commented\n"
    "Environment=PYTHONPATH=/x \\\n# a comment\n  HF_TOKEN=hf_after\n"
    "ExecStart=/opt/venv/bin/vllm serve m --api-key k --hf-token t\n"
    "ExecStart = /opt/vllm serve --api-key execspaced\n"
    "Environment=FOO=it's HF_TOKEN=hf_leak3\n"
    "##Environment=HF_TOKEN=hf_leak4\n"
    "Environment=WINPATH=C:\\\\\n"
    "Environment=HF_TOKEN=\"hf_unclosed tail_unclosed\n"
    "Environment=A=1 \\\r\n  HF_TOKEN=hf_crlf\r\n"
    "Environment=HF_TOKEN\\x3dLEAKESC\n"
    "Environment=HF\\x5fTOKEN=LEAKESC2 PYTHONPATH=/x\n"
    "ExecStart=/opt/vllm serve --api-key k_leak\n"
)
SERVER_SECRETS = ("hf_x", "hf_cont", "abc", "hf_spaced", "pw_one", "two'", "hf_commented", "hf_after",
                  "hf_leak3", "hf_leak4", "hf_unclosed", "tail_unclosed", "hf_crlf", "LEAKESC", "LEAKESC2")


def test_mask_unit_text():
    masked = mask_unit_text(UNIT_TEXT)
    assert not any(secret in masked for secret in (*SERVER_SECRETS, "execspaced", "k_leak")) and " k " not in masked
    assert "HF_TOKEN=<HF_TOKEN>" in masked and "--api-key <VLLM_API_KEY>" in masked and "PYTHONPATH=/x" in masked
    assert "Environment=<masked> PYTHONPATH=/x" in masked.splitlines() and "<masked>" in masked


def test_cgroup_command_rejects_bad_paths():
    assert cgroup_command("system.slice/x") is None and cgroup_command("/a/../b") is None


@pytest.mark.skipif(shutil.which("awk") is None, reason="needs awk")
def test_env_filter_awk_drops_secret_values():
    show = SHOW.replace(
        "Environment=VLLM_API_KEY=k HF_TOKEN CUDA_VISIBLE_DEVICES=0,1 PYTHONPATH=/x",
        'Environment=VLLM_API_KEY=k "HF_TOKEN=hf_a b" CUDA_VISIBLE_DEVICES=0,1 PYTHONPATH=/x',
    ).replace("ControlGroup=", "Environment=MSG=don't HF_TOKEN=hf_leak1\nstray_secret_line\n"
              "Environment=WIN=C:\\ HF_TOKEN=hf_leak2\nEnvironment=\"HF_TOKEN=hf_open hf_tail\nControlGroup=")
    out = subprocess.run(["awk", ENV_FILTER_AWK], input=show, capture_output=True, text=True).stdout
    assert "HF_TOKEN" in out and "VLLM_API_KEY=k" in out and "hf_" not in out
    assert "PYTHONPATH=/x" in out and "stray_secret_line" not in out and "hf_leak1" not in out


@pytest.mark.skipif(shutil.which("awk") is None, reason="needs awk")
def test_unit_mask_awk_masks_secrets():
    out = subprocess.run(["awk", UNIT_MASK_AWK], input=UNIT_TEXT, capture_output=True, text=True).stdout
    assert not any(secret in out for secret in SERVER_SECRETS)
    assert "ExecStart=/opt/vllm serve --api-key k_leak" in out.splitlines()  # not joined into the Environment line
    assert "HF_TOKEN=<HF_TOKEN>" in out
    assert "Environment=<masked> PYTHONPATH=/x" in out.splitlines() and "<masked>" in out
