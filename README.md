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
- **Host keys remembered:** vservx records each server's host key on the first successful login and refuses to connect if it changes, until an operator of its workspace accepts the new key.
- Import from `~/.ssh/config`: upload your SSH config to get pre-filled servers to review; nothing is saved until you confirm. (In the API today; the web app shows it as coming soon.)
- Nothing is installed on the remote server, and nothing on the machine running vservx (its `~/.ssh`, agent or config) is used

### Discovery
vservx watches every saved server that has passed a connection test, all the time, over one SSH connection per server that it keeps open. It looks for vLLM containers every minute (and when you press Refresh). Nothing is installed on the server, but it needs:

- **Docker.** vLLM instances run in Docker containers, found with `docker ps` and `docker inspect`. A container counts as vLLM when its image or its command mentions vLLM, so custom images are found too. (systemd services and plain processes aren't found yet.)
- **`nvidia-smi`** for the GPU panel. Optional.
- **SSH TCP forwarding** (`AllowTcpForwarding`, on by default) **or `curl`** on the server, to reach vLLM's port from the server's own side. vLLM's port never needs to be exposed.

**Docker through sudo.** If your user can't run `docker` directly, vservx tries `sudo -n docker`, then `sudo` with a password: the server's sign-in password, or the sudo password in its settings for servers that sign in with a key. The password goes to sudo on standard input, never on a command line, and only `docker ps` and `docker inspect` ever run through sudo. The safer setup is a sudoers rule that lets your user run only docker without a password, which vservx picks up by itself:

```
<user> ALL=(root) NOPASSWD: /usr/bin/docker
```

**Which servers are watched.** Servers marked "jump host only" aren't searched. A server is watched only once a connection test has recorded its host key (and its jump hosts'), so vservx never starts trusting a key in the background. A rejected sign-in stops the watching until the server's settings change or a connection test passes, instead of retrying a wrong password.

**A container's environment.** Non-secret env vars come back in full, for snapshots. Secret-looking ones are filtered on the server, inside the `docker inspect` template, so only their names cross SSH. A name counts as secret when, upper-cased, it contains `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `API_KEY`, `ACCESS_KEY`, `PRIVATE_KEY` or `CREDENTIAL`, or ends in `_KEY` (so `HF_TOKEN`, `OPENAI_API_KEY` and `AWS_SECRET_ACCESS_KEY` are caught). The one exception is `VLLM_API_KEY`: its value is held in memory only, to ask `/v1/models` for the context length and to fingerprint it. If a server's Docker is too old to run the filter, every env var comes back as a name only.

Each instance shows its state (Ready, Starting, Not responding, Restarting, Crashed, Stopped, Paused), model, port, context length, GPUs, image and vLLM version. A crashed container shows its exit code, whether it ran out of memory, and how often Docker restarted it.

### Metrics
Every 5 seconds vservx reads each ready instance's `/health` and Prometheus `/metrics` through the SSH connection, and keeps:

- **Load:** running and waiting requests
- **KV cache:** cache usage percentage
- **Throughput:** prompt and output tokens per second
- **Latency:** time to first token, averaged over the last minute
- **GPU:** utilization, memory and temperature from `nvidia-smi`, and which containers use each GPU

30 minutes of history is kept in memory for the charts; it starts again empty when vservx restarts. Longer history is Prometheus's job (see Integrations).

### Snapshots
vservx remembers how each vLLM container was launched, so a container that's gone can be started again and a redeploy can be traced. Open them with **Snapshots** in the server's header, or the history icon on an Instances row.

- **Automatic capture.** A snapshot is taken the first time vservx sees a container, and again whenever it's recreated or its launch config changes. Restarts, reordered env vars and vservx restarting don't count as changes.
- **A command to bring it back.** Each snapshot shows a rebuilt `docker run` with Copy. Secrets appear as placeholders such as `-e HF_TOKEN=<HF_TOKEN>` and `--api-key <VLLM_API_KEY>`, left unquoted so pasting one unfilled fails in the shell. A line under it lists what the rebuild covers, and containers started by docker compose say so.
- **Change list and compare.** Per container and for the whole server, newest first: when it happened, the kind (first seen, recreated, recreated with the same config, changed, removed), what differs from the snapshot before, and the container IDs. Any two snapshots on a server can be compared, with their commands as a line diff. A container recreated in the last 24 hours gets a "changed" tag in the table.
- **Removed containers.** A container that's `docker rm`'d keeps its snapshots. It stays greyed in the Instances table for 7 days and in the server's change list for good. Nothing is marked removed when the server can't be reached or `docker ps` fails.
- **API key fingerprint.** The vLLM API key is kept only as an 8-character keyed fingerprint (HMAC, keyed from vservx's key file). **Check a key** tells anyone whether a key they found matches, at most 10 times a minute per person. No secret value is ever stored.

### Management
- **Stop / Force kill / Restart:** uses the right mechanism for each launch type (Docker, systemd, or process signals)
- **Start:** launch a new instance from a form or a raw command, run as a managed Docker container or `systemd-run` unit
- **Preflight checks:** before starting, checks that the port is free, there is enough GPU memory, and the model is cached
- **Pre-stop snapshots:** take a snapshot before every stop, once stopping from vservx exists
- **Logs:** view and tail instance logs
- **Test:** send a small completion request and see the response and latency
- **Confirmations:** destructive actions show in-flight requests and ask before running

### Integrations
- **`/metrics`:** re-exports vLLM metrics with `server`, `instance`, and `model` labels for Prometheus
- **Service discovery:** `/sd` endpoint for Prometheus `http_sd_configs`
- **Grafana:** ready-made dashboard JSON
- **OpenTelemetry:** managed instances can send traces to an OTLP endpoint

## Accounts and workspaces

### Accounts

- **Signing up:** anyone can ask for an account from the sign-in page. The account waits until an app admin approves it; signing in before then says "Your account is waiting for approval". Rejecting a sign-up deletes it.
- **The sign-up switch:** an admin can close sign-up under Admin → Accounts. The sign-in page then has no "Create an account" link.
- **Admin or member:** admins approve sign-ups, make or remove admins, disable accounts and set new passwords, see every workspace and change its owner, and run database upgrades. Everyone else is a member. vservx always keeps at least one active admin.
- **Sessions:** signing in to the web app sets an HttpOnly session cookie that lasts 7 days (`VSERVX_ACCESS_TOKEN_MINUTES`). Changing your password signs out your other sessions, and Account → Sign out everywhere signs out all of them, this one included. API clients can use the bearer token from `POST /api/auth/login` instead.
- **Password guessing:** after 20 failed sign-ins from one address within 15 minutes, or 100 for one email from any number of addresses, sign-in answers 429 until the oldest of them is 15 minutes old, without checking the password. Sign-up allows 5 requests per address per hour. The counts are kept in memory, so a restart clears them. Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to the proxy's address so uvicorn reads each client's address from `X-Forwarded-For`; otherwise every client counts as the proxy.

### Workspaces

Servers and saved keys belong to a workspace, and only its members see them. Anyone with an approved account can create a workspace and becomes its owner. Each member has a role:

| | Viewer | Operator | Owner |
|---|:-:|:-:|:-:|
| See servers, saved keys (never the key itself), members and test results | ✓ | ✓ | ✓ |
| Test a saved server's connection | ✓ | ✓ | ✓ |
| Add, edit and delete servers and saved keys; accept a changed host key | | ✓ | ✓ |
| Add and remove members, and change their roles | | | ✓ |
| Rename the workspace, hand it to another member, delete it | | | ✓ |
| Leave the workspace | ✓ | ✓ | after handing it over |

A workspace always has exactly one owner. An app admin only sees inside workspaces they're a member of; Admin → Workspaces lists every workspace and can give any of them a new owner.

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
| Frontend | Svelte 5 + Vite, TypeScript, Tailwind CSS with shadcn-svelte |
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

Run a single vservx process. Each process watches every server, so several workers would watch them all several times over.

### Run the web app

The web app lives in `ui/` and needs Node.js 20.19 or newer. In development, start the backend on port 8000 as above, then from `ui/`:

```bash
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server passes `/api` requests on to the backend, so no CORS setup is needed.

For production, build it once from `ui/`:

```bash
npm run build
```

FastAPI then serves `ui/dist` at http://127.0.0.1:8000 next to the API, so vservx stays one process. Set `VSERVX_UI_DIR` to serve a build from somewhere else.

After changing the API, regenerate the web app's types from `ui/` (it runs the backend's Python from `.venv` to read the OpenAPI schema):

```bash
npm run gen:api
```

### Test

From `backend/`:

```bash
pytest
```

Tests use a temporary data directory and never touch your real database.

From `ui/`, `npm test` runs the unit tests and `npm run check` type-checks the app.

### Configuration

Settings come from `VSERVX_*` environment variables or a `.env` file in the directory the app is started from. `backend/.env.example` lists every option with its default. Those for watching servers:

| Setting | Default | |
|---|---|---|
| `VSERVX_WATCH_ENABLED` | `true` | Watch servers at all |
| `VSERVX_USAGE_INTERVAL_SECONDS` | `5` | How often health, usage and GPUs are read |
| `VSERVX_DISCOVERY_INTERVAL_SECONDS` | `60` | How often vLLM containers are looked for |
| `VSERVX_HISTORY_MINUTES` | `30` | Usage history kept in memory for the charts |
| `VSERVX_WATCH_CONCURRENCY` | `8` | Most servers doing SSH work at the same moment |

Local data lives in `~/.config/vservx/` (override with `VSERVX_DATA_DIR`). This directory is the one thing to back up, and the one volume to mount when running in Docker:

| File | Purpose |
|---|---|
| `vservx.db` | SQLite database |
| `secret.key` | Encrypts stored passwords and saved keys. Back it up: without it, they can't be read. |
| `jwt.key` | Signs login tokens. Deleting it signs everyone out. |
| `backups/` | A copy of `vservx.db` made before each database upgrade. Never deleted automatically. |

### Database upgrades

A new version of vservx can change the database's tables. vservx never changes an existing database on its own: when it starts on a database that is older than the code, it waits until someone runs the upgrade. While it waits, `/api/health` reports `"database": "upgrade_required"`, only app admins can sign in, and every other API call returns 503 with `"code": "database_upgrade_required"`.

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