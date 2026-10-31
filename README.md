# vservx

> Point it at a server, see your vLLMs. No agents, no config.

**vservx** ("vLLM-serve-all") is a lightweight, agentless tool for monitoring and managing vLLM instances on remote GPU servers. It connects over SSH, finds every running vLLM instance, and shows its health, load, and GPU usage in a web dashboard. You don't install anything on the servers.

## Why

On bare GPU servers, checking which models are running, on which ports, and how busy they are usually means SSH-ing into each box and running commands by hand. Starting and stopping instances is manual too. vservx puts all of that in one place.

## Key Components

### SSH Connection
- Connect with host, port, username, and a password or a saved key
- **Saved keys:** upload or paste a private key once, give it a name, and pick it for any number of servers. Replacing it updates every server that uses it.
- **Jump hosts:** any saved server can be the jump host for another, and chains can be any length (laptop → bastion-1 → bastion-2 → gpu-7). Each hop uses its own credentials.
- **Connection test:** test a saved server, or its settings before saving. The result shows each hop in order and, if one fails, which one and why.
- **Host keys remembered:** vservx records each server's host key on the first successful login and refuses to connect if it changes, until an admin accepts the new key.
- Import from `~/.ssh/config`: upload your SSH config to get pre-filled servers to review; nothing is saved until you confirm.
- Nothing is installed on the remote server, and nothing on the machine running vservx (its `~/.ssh`, agent or config) is used

### Discovery
Finds vLLM instances however they were launched:

| Launch method | How it's detected |
|---|---|
| Docker | `docker ps` filtered by the `vllm/vllm-openai` image or command |
| systemd | `systemctl list-units` matching vllm |
| Bare process | `ps` matching `vllm serve` / `vllm.entrypoints` |

Each candidate is confirmed by calling `/v1/models` on its port.

### Metrics
vservx reads vLLM's Prometheus `/metrics` endpoint through the SSH session, so vLLM ports never need to be exposed. It tracks:

- **Load:** running and waiting requests
- **KV cache:** cache usage percentage
- **Latency:** time to first token, time per output token, end-to-end latency
- **Throughput:** prompt and generation tokens
- **Pressure:** preemptions
- **GPU:** utilization and memory from `nvidia-smi`, mapped to vLLM processes

About 15 minutes of history is kept in memory for live charts.

### Management
- **Stop / Force kill / Restart:** uses the right mechanism for each launch type (Docker, systemd, or process signals)
- **Start:** launch a new instance from a form or a raw command, run as a managed Docker container or `systemd-run` unit
- **Preflight checks:** before starting, checks that the port is free, there is enough GPU memory, and the model is cached
- **Snapshots:** saves an instance's launch config automatically on discovery and before every stop, or on demand
- **Logs:** view and tail instance logs
- **Test:** send a small completion request and see the response and latency
- **Confirmations:** destructive actions show in-flight requests and ask before running

### Integrations
- **`/metrics`:** re-exports vLLM metrics with `server`, `instance`, and `model` labels for Prometheus
- **Service discovery:** `/sd` endpoint for Prometheus `http_sd_configs`
- **Grafana:** ready-made dashboard JSON
- **OpenTelemetry:** managed instances can send traces to an OTLP endpoint

## Architecture

```
┌──────────────┐        ┌───────────────────────────┐        SSH        ┌──────────────────┐
│   Browser    │ <────> │    vservx (FastAPI)       │ <───────────────> │  GPU Server(s)   │
│   (Svelte)   │  JSON  │  - SSH pool (asyncssh)    │                   │  - vLLM (docker/ │
└──────────────┘  +SSE  │  - discovery              │                   │    systemd/proc) │
                        │  - metrics poller         │                   │  - nvidia-smi    │
                        │  - actions + snapshots    │                   └──────────────────┘
                        │  - SQLite                 │
                        │  - /metrics  /sd endpoint │
                        └─────────────┬─────────────┘
                                      │ scrape
                              ┌───────▼───────┐      ┌──────────┐
                              │  Prometheus   │ ───> │ Grafana  │
                              └───────────────┘      └──────────┘
```

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI |
| SSH | asyncssh |
| Metrics export | prometheus_client |
| Storage | SQLite, created automatically at `~/.config/vservx/vservx.db` |
| Secrets | Encrypted at rest (Fernet) |
| Frontend | Svelte + Vite |
| Charts | uPlot |
| Live updates | Server-Sent Events (SSE) |

## Development

Requires Python 3.11 or newer. The backend lives in `backend/`, and its dependencies are declared in `backend/pyproject.toml`.

### Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
cd backend
pip install -e ".[dev]"
cp .env.example .env             # optional; Windows: copy .env.example .env
```

`-e` installs the project in editable mode, so code changes apply without reinstalling. `[dev]` adds the test dependencies.

### Run

From `backend/`:

```bash
python -m api.main
```

The API starts on http://127.0.0.1:8000 with auto-reload, and interactive docs are at http://127.0.0.1:8000/docs.

On first start, vservx creates an admin account and prints its generated password to the console once. To choose the credentials yourself, set `VSERVX_ADMIN_EMAIL` and `VSERVX_ADMIN_PASSWORD` before the first start.

### Test

From `backend/`:

```bash
pytest
```

Tests use a temporary data directory and never touch your real database.

### Configuration

Settings come from `VSERVX_*` environment variables or a `.env` file in the directory the app is started from. `backend/.env.example` lists every option with its default.

Local data lives in `~/.config/vservx/` (override with `VSERVX_DATA_DIR`). This directory is the one thing to back up, and the one volume to mount when running in Docker:

| File | Purpose |
|---|---|
| `vservx.db` | SQLite database |
| `secret.key` | Encrypts stored passwords and saved keys. Back it up: without it, they can't be read. |
| `jwt.key` | Signs login tokens. Deleting it signs everyone out. |
| `backups/` | A copy of `vservx.db` made before each database upgrade. Never deleted automatically. |

### Database upgrades

A new version of vservx can change the database's tables. vservx never changes an existing database on its own: when it starts on a database that is older than the code, it waits until someone runs the upgrade. While it waits, `/api/health` reports `"database": "upgrade_required"`, signing in still works, and every other API call returns 503 with `"code": "database_upgrade_required"`.

An admin runs the upgrade in either of two ways:

- **In the UI:** the upgrade notice's button, which calls `POST /api/database/upgrade`. `GET /api/database` lists what the upgrade will change.
- **From the command line:** `vservx db upgrade`, or `docker exec <container> vservx db upgrade` in Docker. `vservx db status` shows whether an upgrade is waiting.

Both back up the database to `backups/` first, then apply every change in one transaction, so a failed upgrade leaves the database as it was. vservx carries on without a restart, and `GET /api/database` reports when the last upgrade happened and who ran it.

To go back to a backup: stop vservx, replace `vservx.db` with the backup file, delete `vservx.db-wal` and `vservx.db-shm` if they exist, then start the vservx version that matches the backup. A newer vservx's database can't be opened by an older version; vservx reports `"database": "newer_than_app"` instead.

A database created before vservx had migrations can't be upgraded. vservx refuses to start on one: move it aside or delete it, and vservx creates a new one.

### Schema changes

The tables are defined by the models in `backend/api/models/`. After changing a model, generate a migration from `backend/`:

```bash
alembic revision --autogenerate -m "Add GPU details to instances"
```

Review the generated file in `api/db/migrations/versions/` and commit it with the model change. The message is shown to users in the upgrade notice, so write it in plain words. Then upgrade your own database with `vservx db upgrade`. `tests/test_database.py` fails if a model change has no migration.