# vservx

> Point it at a server, see your vLLMs. No agents, no config.

**vservx** ("vLLM-serve-all") is a lightweight, agentless tool for monitoring and managing vLLM instances on remote GPU servers. It connects over SSH, finds every running vLLM instance, and shows its health, load, and GPU usage in a web dashboard. You don't install anything on the servers.

## Why

On bare GPU servers, checking which models are running, on which ports, and how busy they are usually means SSH-ing into each box and running commands by hand. Starting and stopping instances is manual too. vservx puts all of that in one place.

## Key Components

### SSH Connection
- Connect with host, port, username, and a password or key file
- Import hosts from `~/.ssh/config`
- Manage multiple servers at once
- Nothing is installed on the remote server

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
