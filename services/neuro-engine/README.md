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
| `GET /health` | `ok`, or `degraded` with `degradedReasons`: `not-streaming` (state is not `streaming`), `no-recent-data` (no accepted block within 3 block durations, at least 1 s), `recent-rejections` (a device block was rejected within that window). Also protocol version, acquisition summary and counters |
| `GET /api/v2/stream` | Current `stream.metadata` (or `null`) and `stream.status` |
| `WS /ws/v2/eeg` | Metadata (when a stream is open), then status, then `eeg.block` messages and periodic status; metadata is re-sent whenever a new stream opens. Browser `Origin` must be in the allowlist (otherwise the handshake is rejected); client messages close with 1003; a message that cannot be encoded closes with 1011; if the engine closes the client's subscription the socket closes with 1013 (try again later) |

## Adapter contract

Adapters implement `acquisition.base.DeviceAdapter`. Descriptors are checked against the protocol v2 limits when constructed (violations are non-retryable `DeviceConfigError`). Sample indices start at 0 after `open()`, never wrap and are derived from device counters; if an adapter cannot tell how many samples were lost it raises `DeviceDisconnectedError` so a new stream starts. The service rejects and counts malformed, duplicate, overlapping or out-of-range blocks (one non-finite value rejects the whole block; see ADR-0009), splits blocks larger than 10 000 samples without changing values, and logs `close()` failures without letting them replace the session outcome.

## Configuration (environment)

| Variable | Default | Notes |
| --- | --- | --- |
| `NEURO_ENGINE_DEVICE` | `synthetic` | Only `synthetic` is implemented |
| `NEURO_ENGINE_SYNTHETIC_SEED` | `0` | Same seed + config ⇒ bit-identical samples |
| `NEURO_ENGINE_SYNTHETIC_BLOCK_SIZE` | `25` | Samples per block (200 ms at 125 Hz) |
| `NEURO_ENGINE_LIVE_VIEW_QUEUE_BLOCKS` | `25` | Per-client queue bound; oldest blocks are dropped and counted |
| `NEURO_ENGINE_ALLOWED_ORIGINS` | Vite dev/preview on `localhost`/`127.0.0.1` ports 4200 and 4300 | Comma-separated |

Invalid values fail at startup.

## Reference anatomy (datasets and cortical assets)

Decision record: [ADR-0010](../../docs/architecture/decisions/ADR-0010-reference-anatomy-foundation.md). Frames, units, the asset contract and what source estimation still needs: [ANATOMY.md](../../docs/architecture/ANATOMY.md).

Nothing is downloaded automatically: not at engine startup, from the UI, or in CI. Every download is a CLI command you run.

### Setup

```bash
cd services/neuro-engine
uv sync                         # core: nibabel is enough for IXI, ds000248, prepare and serving
uv sync --extra neuroimaging    # adds mne + mne-bids: needed for `fetch fsaverage` and `inspect-eeg`
```

### Storage

All data lives under one root, outside the repository:

| Platform | Default |
| --- | --- |
| macOS | `~/Library/Application Support/NeuroObservatory` |
| Linux/other | `$XDG_DATA_HOME/neuro-observatory`, else `~/.local/share/neuro-observatory` |

Override with `NEURO_ENGINE_DATA_DIR=/path` or `neuro-engine --data-dir /path ...`. The engine's anatomy API reads the same setting. A root inside a Git working tree is refused unless Git ignores it. Layout: `raw/<dataset>/<version>/` (verified source files and `<version>.acquisition.json`), `derivatives/<dataset>/<version>/`, `downloads/` (resumable `*.part`; safe to delete), `assets/anatomy/<assetId>/` (regenerable). Remove everything with `rm -rf "<root>"`.

Disk use measured on 2026-10-30:

| Item | Download | On disk |
| --- | --- | --- |
| fsaverage (MNE, two OSF archives) | 0.43 GB | 761 MB |
| ds000248 `1.2.4`, `anatomy` profile (36 files) | 202 MB | 199 MB |
| ds000248 `1.2.4`, `full` profile (1 229 files; needs `--confirm-large`) | 2.07 GB (listing) | not downloaded |
| IXI012-HH-1211 T1 (one member of the 4.84 GB `IXI-T1.tar`) | 10.1 MB | 10 MB |
| One prepared asset (pial, white, inflated, atlases) | — | 36–37 MB |

### Commands

```bash
uv run neuro-engine datasets list                         # catalog, licence, acquisition status
uv run neuro-engine datasets info ds000248                # source, DOI, licence, attribution, notes
uv run --extra neuroimaging neuro-engine datasets fetch fsaverage --accept-license   # FreeSurfer licence
uv run neuro-engine datasets fetch ds000248               # anatomy profile; --profile full --confirm-large for all
uv run neuro-engine datasets fetch ixi --subject IXI012-HH-1211 --accept-license     # CC BY-SA 3.0; range fetch
uv run neuro-engine datasets import ixi ~/Downloads/IXI012-HH-1211-T1.nii.gz --accept-license
uv run neuro-engine datasets validate ds000248            # re-hash every file against acquisition.json
uv run neuro-engine datasets subjects                     # e.g. fsaverage, ds000248/sub-01, ixi/IXI012-HH-1211
uv run neuro-engine datasets check-subject ds000248/sub-01   # BIDS, landmarks, rawavg vs T1w, EEG presence
uv run --extra neuroimaging neuro-engine datasets inspect-eeg ds000248/sub-01   # metadata only
uv run neuro-engine anatomy check-mri <file.nii.gz|file.mgz> # FreeSurfer-input checks; does not resample
uv run neuro-engine anatomy prepare fsaverage             # or ds000248/sub-01; --surfaces, --atlas
uv run neuro-engine anatomy assets                        # * marks the viewer default
uv run neuro-engine anatomy verify <assetId>
```

Global options: `--data-dir`, `--json`. Exit code 0 = ok, 1 = failed check or error (printed as `error [code]: message` plus a `hint:`), 2 = usage error. Downloads are idempotent (verified files are skipped) and resume from `downloads/*.part`; a size or checksum mismatch deletes the partial file and fails.

To view anatomy: prepare at least one subject, start the engine (`yarn nx run neuro-engine:serve`) and the desktop (`yarn nx serve desktop`). The engine rescans prepared assets on every catalog request; choose **Refresh subjects** in the viewer to see new ones (no restart of either process).

| Path | Description |
| --- | --- |
| `GET /api/anatomy/v1/catalog` | Prepared assets and the default (newest template) |
| `GET /api/anatomy/v1/assets/{assetId}/manifest.json` | `anatomy-asset.v1` manifest |
| `GET /api/anatomy/v1/assets/{assetId}/files/{name}` | Buffers listed in the manifest only |

CORS on these routes: GET only, origins from `NEURO_ENGINE_ALLOWED_ORIGINS`. MRI voxels are never served.

### Adding subjects

- **Another ds000248 subject or file**: the `full` profile fetches the whole snapshot; any `sub-*` with a FreeSurfer directory under `derivatives/freesurfer/subjects/` appears in `datasets subjects`.
- **Another IXI subject**: `fetch ixi --subject IXI<nnn>-<site>-<id>` (site HH, Guys or IOP; only HH is 3 T) or `import ixi <file>`. IXI T1s have no FreeSurfer reconstruction; see [`pipelines/mri-reconstruction`](../../pipelines/mri-reconstruction/README.md).
- **Your own MRI** (anatomy kind `personal`, stored under `raw/local/1/`, never committed):
  1. `datasets import-mri <T1.nii.gz> --label me --field-strength 3 --sequence MPRAGE --scanner "<model>"` (a pseudonymous label; facts are recorded as `user-declared`; the original path is not recorded).
  2. `anatomy check-mri` on the imported file, then reconstruct it outside the engine (see the pipeline README).
  3. `datasets import-freesurfer <SUBJECTS_DIR>/<subject> --label me`, then `anatomy prepare local/me`.

  Personal MRI-derived meshes are restricted data: they stay in the data root and are served only on loopback.

### Tests

`yarn nx run neuro-engine:test` uses synthetic fixtures generated at test time and needs no network. Real-data checks are opt-in and skip with a reason when data or MNE is missing:

```bash
NEURO_ENGINE_DATA_DIR="$HOME/Library/Application Support/NeuroObservatory" yarn nx run neuro-engine:test-integration
```

## Layout

- `acquisition/` — `DeviceAdapter` protocol, typed device errors, `SampleBlock`, clocks, synthetic adapter (with drop/disconnect fault injection), `AcquisitionService` state machine.
- `streaming/hub.py` — `StreamHub` fan-out with `live-view` and `lossless` delivery policies.
- `protocol/` — Pydantic mirror of the canonical schema, semantic validation, converters, integrity tracker.
- `api/` — HTTP and WebSocket routes. `app.py` wires the lifespan; `config.py` reads settings.
