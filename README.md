# JARVIS Event Stream

Internal JARVIS service that stores RunEvents and serves NDJSON streams.
This is a JARVIS-only contract (not part of the ARP Standard).

## Requirements

- Python >= 3.11

## Install

```bash
python3 -m pip install -e .
```

## Run

```bash
python3 -m pip install -e .
arp-jarvis-eventstream
```

> [!TIP]
> Use `bash src/scripts/dev_server.sh --host ... --port ... --reload` for dev convenience.

## Configuration

Environment variables:
- `JARVIS_EVENT_STORE_DB_URL` (default `sqlite:///./runs/jarvis_event_store.sqlite`)
- `JARVIS_EVENT_RETENTION_DAYS` (optional)
- `ARP_AUTH_*` (JWT auth settings, shared across JARVIS services)

Auth is enabled by default (JWT). To disable for local dev, set `ARP_AUTH_PROFILE=dev-insecure`
or `ARP_AUTH_MODE=disabled`. Health/version endpoints are always exempt.
If no `ARP_AUTH_*` env vars are set, the service defaults to the dev Keycloak issuer.

## API (v0.3.7)

Health/version:
- `GET /v1/health`
- `GET /v1/version`

Events:
- `POST /v1/run-events` -> `{ items: [{ run_id, seq }], next_seq_by_run: { run_id: seq } }`
- `GET /v1/runs/{run_id}/events` (NDJSON)
- `GET /v1/node-runs/{node_run_id}/events` (NDJSON)

Query params for streams:
- `cursor` (opaque, optional)
- `follow` (0/1, optional)
- `limit` (optional)
