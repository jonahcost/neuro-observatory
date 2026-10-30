# System architecture and invariants

**Status:** Design baseline. Verify implemented code before claiming a subsystem exists.

## Components and ownership

| Area | Source | Responsibility | Never owns |
| --- | --- | --- | --- |
| `apps/desktop` | React/Vite/Three.js | UI, charts, 3D visual state | Raw acquisition, medical conclusions, session source of truth |
| `services/neuro-engine` | Python/FastAPI/uv | Device adapters, DSP, recording, dataset acquisition and anatomy assets, source estimates (as built) | GPU display code |
| `packages/protocol` | JSON Schema (canonical) + TS validator/types; Python mirror in the engine | Stable, versioned producer/consumer contract and shared fixtures | Private samples or user data |
| `pipelines/*` (future; `mri-reconstruction` is documented, not automated) | MRI/ML batch jobs | Reproducible reconstructions and training | Time-critical acquisition loop |
| `hardware/*` (future) | CAD/PCB/firmware | Physical acquisition designs, simulator-only validation until safety clearance | Clinical-use certification claims |
| `apps/hologram` (future) | Display adapter | Spatial renderer | Acquisition, source-estimation math |

## Canonical flow

Physical or synthetic EEG -> device adapter -> immutable raw ring buffer / local recorder -> quality-aware DSP -> source model / inference -> versioned scene frame -> desktop or holographic adapter. Sensor synchronization and experiment markers use explicit timebase metadata. Replay uses the same ingestion interface.

## Implemented acquisition path (Milestone 01A, ADR-0008)

```text
SyntheticEegAdapter (DeviceAdapter)          engine process, started by FastAPI lifespan
  -> AcquisitionService   stream IDs, sample-index integrity, gap derivation, reconnect, counters
  -> StreamHub            non-blocking publish; bounded queue per subscriber
       |- live-view subscriber per WebSocket client (drop oldest + count)
       '- lossless subscriber (reserved: recorder, 01B+) fails explicitly on overflow
  -> /ws/v2/eeg           protocol v2 JSON (stream.metadata, eeg.block, stream.status), Origin allowlist, 127.0.0.1
  -> EegStreamClient      desktop; validates every message, integrity tracker, reconnect/stale/incompatible states
       |- onBlock()       sample consumers (future waveform ring buffer); never React state
       '- snapshot        throttled status for React (useSyncExternalStore)
```

Acquisition runs whether or not any client is connected. Recording, replay, DSP and the waveform buffer are not implemented yet; their seams are the lossless `StreamHub` subscription, the `DeviceAdapter` protocol, and `EegStreamClient.onBlock`. The wire contract is documented in [`packages/protocol/README.md`](../../packages/protocol/README.md).

## Implemented anatomy path (Milestone 02A, ADR-0010)

```text
neuro-engine datasets fetch|import ...     CLI, explicit; verified, resumable; per-user data root outside the repo
  -> raw/<dataset>/<version>/ + acquisition.json (provenance, licence, checksums)
neuro-engine anatomy prepare <subject>     FreeSurfer surfaces -> anatomy-asset v1 (mm, surface RAS, full resolution)
  -> GET /api/anatomy/v1/...               read-only, 127.0.0.1, CORS allowlist
  -> AnatomyViewer                         desktop; verifies buffers, renders both hemispheres, labels anatomy kind
```

The anatomy path is offline batch code plus a read-only API; acquisition never imports it. The viewer shows anatomy only: no EEG channel is mapped to the cortex and no source estimate exists. Details, coordinate frames and the remaining steps toward source estimation are in [ANATOMY.md](ANATOMY.md).

## Non-functional requirements

1. **Local-first security:** no cloud by default, loopback APIs, private recordings excluded from Git.
2. **Acquisition integrity:** bounded queues; record gaps, counters, overflows and bad contacts. Rendering/ML cannot block raw ingestion.
3. **Scientific provenance:** measured EEG != inverse-solver-estimated cortex != ML-labeled state. UI differentiates clearly.
4. **Reproducibility:** version acquisition firmware, channel map, EEG reference, filter settings, montage, MRI transforms, inverse operator and model.
5. **Modularity:** new hardware implements adapter interface; different display implements renderer interface. Avoid assumptions of exactly 16 channels.
6. **Safe expansion:** custom PCBs only use dummy loads until qualified safety review; MRI and face geometry are sensitive.

See [ADRs](decisions/README.md), [infrastructure policy](../standards/infrastructure.md), and [scientific integrity](../standards/scientific-integrity.md).
