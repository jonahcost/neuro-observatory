# Neuro Engine

Local Python service (FastAPI, uv) that owns EEG acquisition and streams protocol v2 to local clients. Decision record: [ADR-0008](../../docs/architecture/decisions/ADR-0008-eeg-acquisition-protocol-foundation.md). Wire contract: [`packages/protocol`](../../packages/protocol/README.md).

The only source currently implemented is the **deterministic synthetic generator** (16 channels, 125 Hz, alpha 10 Hz + theta 6 Hz + Gaussian noise). Its output is labelled `synthetic` in every metadata message and is not a measurement of a person.

## Run

```bash
yarn nx run neuro-engine:serve      # uvicorn on 127.0.0.1:8000 with --reload
yarn nx run neuro-engine:test       # uv run pytest
yarn nx run neuro-engine:lint       # uv run ruff check .
```

Acquisition starts with the application lifespan and runs whether or not any client is connected.

## Endpoints (loopback only)

| Path | Description |
| --- | --- |
| `GET /health` | Service status (`degraded` when acquisition failed), protocol version and acquisition summary |
| `GET /api/v2/stream` | Current `stream.metadata` (or `null`) and `stream.status` |
| `WS /ws/v2/eeg` | Metadata, then status, then `eeg.block` messages and periodic status. Browser `Origin` must be in the allowlist (otherwise the handshake is rejected); client messages close with 1003; if the engine closes the client's subscription the socket closes with 1013 (try again later) |

## Configuration (environment)

| Variable | Default | Notes |
| --- | --- | --- |
| `NEURO_ENGINE_DEVICE` | `synthetic` | Only `synthetic` is implemented |
| `NEURO_ENGINE_SYNTHETIC_SEED` | `0` | Same seed + config ⇒ bit-identical samples |
| `NEURO_ENGINE_SYNTHETIC_BLOCK_SIZE` | `25` | Samples per block (200 ms at 125 Hz) |
| `NEURO_ENGINE_LIVE_VIEW_QUEUE_BLOCKS` | `25` | Per-client queue bound; oldest blocks are dropped and counted |
| `NEURO_ENGINE_ALLOWED_ORIGINS` | Vite dev/preview on `localhost`/`127.0.0.1` ports 4200 and 4300 | Comma-separated |

Invalid values fail at startup.

## Layout

- `acquisition/` — `DeviceAdapter` protocol, typed device errors, `SampleBlock`, clocks, synthetic adapter (with drop/disconnect fault injection), `AcquisitionService` state machine.
- `streaming/hub.py` — `StreamHub` fan-out with `live-view` and `lossless` delivery policies.
- `protocol/` — Pydantic mirror of the canonical schema, semantic validation, converters, integrity tracker.
- `api/` — HTTP and WebSocket routes. `app.py` wires the lifespan; `config.py` reads settings.
