# System architecture and invariants

**Status:** Design baseline. Verify implemented code before claiming a subsystem exists.

## Components and ownership

| Area | Source | Responsibility | Never owns |
| --- | --- | --- | --- |
| `apps/desktop` | React/Vite/Three.js | UI, charts, 3D visual state | Raw acquisition, medical conclusions, session source of truth |
| `services/neuro-engine` | Python/FastAPI/uv | Device adapters, DSP, recording, source estimates (as built) | GPU display code |
| `packages/protocol` | TS bootstrap; evolve to neutral schema | Stable, versioned producer/consumer contract | Private samples or user data |
| `pipelines/*` (future) | MRI/ML batch jobs | Reproducible reconstructions and training | Time-critical acquisition loop |
| `hardware/*` (future) | CAD/PCB/firmware | Physical acquisition designs, simulator-only validation until safety clearance | Clinical-use certification claims |
| `apps/hologram` (future) | Display adapter | Spatial renderer | Acquisition, source-estimation math |

## Canonical flow

Physical or synthetic EEG -> device adapter -> immutable raw ring buffer / local recorder -> quality-aware DSP -> source model / inference -> versioned scene frame -> desktop or holographic adapter. Sensor synchronization and experiment markers use explicit timebase metadata. Replay uses the same ingestion interface.

## Non-functional requirements

1. **Local-first security:** no cloud by default, loopback APIs, private recordings excluded from Git.
2. **Acquisition integrity:** bounded queues; record gaps, counters, overflows and bad contacts. Rendering/ML cannot block raw ingestion.
3. **Scientific provenance:** measured EEG != inverse-solver-estimated cortex != ML-labeled state. UI differentiates clearly.
4. **Reproducibility:** version acquisition firmware, channel map, EEG reference, filter settings, montage, MRI transforms, inverse operator and model.
5. **Modularity:** new hardware implements adapter interface; different display implements renderer interface. Avoid assumptions of exactly 16 channels.
6. **Safe expansion:** custom PCBs only use dummy loads until qualified safety review; MRI and face geometry are sensitive.

See [ADRs](decisions/README.md), [infrastructure policy](../standards/infrastructure.md), and [scientific integrity](../standards/scientific-integrity.md).
