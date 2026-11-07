"""The snapshot routes: change lists, one snapshot's command, compare, and Check a key."""

import json
from collections.abc import Awaitable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.models import Snapshot
from tests.helpers import MODEL, SERVER_BODY, Db, FakeVLLM, Sshd, docker_host, wait_for, watched_server


def _stored_snapshots_text(session: AsyncSession) -> Awaitable[str]:
    async def read() -> str:
        return json.dumps([s.config for s in await session.scalars(select(Snapshot))])
    return read()


def test_snapshot_api(watching: None, client: TestClient, api: TestClient, w: str, db: Db, sshd: Sshd,
                      fake_vllm: FakeVLLM, outsider_headers: dict[str, str]) -> None:
    answer = docker_host(fake_vllm, sudo_password="ssh-pw")
    server_id = watched_server(api, w, sshd(password="ssh-pw", commands=answer))
    base = f"{w}/servers/{server_id}"
    entries = lambda: api.get(f"{base}/snapshots").json()["entries"]  # noqa: E731
    wait_for(entries, lambda e: len(e) == 1)
    for n, length in ((2, "8192"), (3, "16384"), (4, "32768")):
        answer.relaunch(str(n) * 64, "--max-model-len", length)
        wait_for(entries, lambda e, n=n: len(e) == n)
    listed = entries()
    assert [e["kind"] for e in listed] == ["recreated", "recreated", "recreated", "first_seen"]
    assert {e["model"] for e in listed} == {MODEL}  # what each one ran, kept per snapshot
    assert len(api.get(f"{base}/instances/vllm-llama/snapshots").json()["entries"]) == 4
    last, second = listed[0]["id"], listed[2]["id"]
    compared = api.get(f"{base}/snapshots/compare", params={"from": last, "to": second}).json()
    assert compared["from_snapshot"]["id"] == second       # the older one, whichever way it was asked
    assert {"label": "--max-model-len", "before": "8192", "after": "32768", "note": None} in compared["differences"]
    detail = api.get(f"{base}/snapshots/{last}").json()
    assert "-e VLLM_API_KEY=<VLLM_API_KEY> \\" in detail["command"] and "-e HF_TOKEN=<HF_TOKEN> \\" in detail["command"]
    assert len(detail["key_fingerprint"]) == 8
    assert api.get(f"{base}/watch").json()["instances"][0]["changed_at"] is not None
    check = f"{base}/snapshots/{last}/check-key"
    assert api.post(check, json={"key": " vllm-key\n"}).json() == {"matches": True, "reason": None}
    assert api.post(check, json={"key": "nope"}).json()["matches"] is False
    codes = [api.post(check, json={"key": "nope"}).status_code for _ in range(9)]
    assert codes[-1] == 429 and codes.count(429) == 1      # the 11th check this minute
    other = api.post(f"{w}/servers", json=SERVER_BODY | {"name": "gpu-8"}).json()["id"]
    assert api.get(f"{w}/servers/{other}/snapshots/compare", params={"from": last, "to": second}).status_code == 404
    assert api.get(f"{w}/servers/{other}/snapshots/{last}").status_code == 404
    for path in (f"{base}/snapshots", f"{base}/snapshots/{last}", f"{base}/instances/vllm-llama/snapshots"):
        assert client.get(path, headers=outsider_headers).status_code == 404
    seen = "".join(api.get(p).text for p in (f"{base}/snapshots", f"{base}/snapshots/{last}", f"{base}/watch"))
    seen += json.dumps(compared) + db(_stored_snapshots_text)
    for secret in ("vllm-key", "hf_secret"):
        assert secret not in seen
