"""recording.v1: a manifest plus channel-major float64 samples.

The file is the raw replay source. Derived findings are not written into it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from neuro_engine.acquisition.base import (
    ChannelSpec,
    DeviceInfo,
    DeviceProvenance,
    StreamDescriptor,
    SyntheticProvenance,
    TimestampSource,
)

RECORDING_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
SAMPLES_NAME = "samples.f64"


class RecordingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class Gap:
    """Samples [first_index, first_index + count) were never stored."""

    first_index: int
    count: int


@dataclass(frozen=True, slots=True)
class Recording:
    recording_id: str
    samples: np.ndarray
    descriptor: StreamDescriptor
    gaps: tuple[Gap, ...]
    directory: Path | None = None

    @property
    def sample_count(self) -> int:
        return int(self.samples.shape[1])


def _sha256(samples: np.ndarray) -> str:
    blob = np.ascontiguousarray(samples, dtype="<f8")
    return "sha256:" + hashlib.sha256(blob.tobytes()).hexdigest()


def _check_id(recording_id: str) -> str:
    if RECORDING_ID.fullmatch(recording_id) is None:
        raise RecordingError("invalid-recording-id", "recording id must be a lowercase slug")
    return recording_id


def present_runs(sample_count: int, gaps: tuple[Gap, ...]) -> tuple[tuple[int, int, int], ...]:
    """Present runs as (sample_index, stored_offset, length)."""
    runs: list[tuple[int, int, int]] = []
    stored = 0
    index = 0
    for gap in gaps:
        if gap.first_index < index or gap.count < 1:
            raise RecordingError("invalid-gap", "gaps must be ordered, non-overlapping, and non-empty")
        if gap.first_index > index:
            length = gap.first_index - index
            runs.append((index, stored, length))
            stored += length
        index = gap.first_index + gap.count
    if stored > sample_count:
        raise RecordingError("invalid-gap", "gaps account for more samples than the file stores")
    if stored < sample_count:
        runs.append((index, stored, sample_count - stored))
    elif stored != sample_count:
        raise RecordingError("invalid-gap", "stored sample count does not match the manifest")
    return tuple(runs)


def cursor_at(recording: Recording, start_index: int) -> tuple[int, int] | None:
    """First present (sample_index, stored_offset) at or after start_index."""
    if start_index < 0:
        raise RecordingError("invalid-seek", "sample index must be non-negative")
    for sample_index, stored, length in present_runs(recording.sample_count, recording.gaps):
        end = sample_index + length
        if end <= start_index:
            continue
        skip = max(0, start_index - sample_index)
        return sample_index + skip, stored + skip
    return None


def write_recording(
    directory: Path,
    samples: np.ndarray,
    descriptor: StreamDescriptor,
    *,
    recording_id: str,
    gaps: tuple[Gap, ...] = (),
) -> Recording:
    recording_id = _check_id(recording_id)
    array = np.ascontiguousarray(samples, dtype="<f8")
    if array.ndim != 2 or array.shape[0] != descriptor.channel_count or array.shape[1] < 1:
        raise RecordingError("invalid-samples", "samples must be shaped (channels, samples)")
    present_runs(int(array.shape[1]), gaps)
    directory.mkdir(parents=True, exist_ok=True)
    blob_path = directory / SAMPLES_NAME
    blob_path.write_bytes(array.tobytes())
    provenance = descriptor.provenance
    if isinstance(provenance, SyntheticProvenance):
        provenance_doc: dict[str, object] = {
            "kind": "synthetic",
            "generator": provenance.generator,
            "generatorVersion": provenance.generator_version,
            "seed": provenance.seed,
            "configHash": provenance.config_hash,
        }
    else:
        provenance_doc = {"kind": "device"}
    manifest = {
        "type": "recording.manifest",
        "schemaVersion": 1,
        "recordingId": recording_id,
        "nominalSampleRateHz": descriptor.nominal_sample_rate_hz,
        "sampleCount": int(array.shape[1]),
        "layout": "channel-major",
        "dtype": "float64",
        "endian": "little",
        "samplesSha256": _sha256(array),
        "timestampSource": descriptor.timestamp_source,
        "device": {
            "kind": descriptor.device.kind,
            "model": descriptor.device.model,
            "deviceId": descriptor.device.device_id,
            "adapterVersion": descriptor.device.adapter_version,
        },
        "provenance": provenance_doc,
        "channels": [
            {
                "index": index,
                "label": channel.label,
                "type": channel.type,
                "unit": channel.unit,
                "reference": channel.reference,
            }
            for index, channel in enumerate(descriptor.channels)
        ],
        "gaps": [{"firstIndex": gap.first_index, "count": gap.count} for gap in gaps],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return Recording(recording_id, array, descriptor, gaps, directory)


def read_recording(directory: Path) -> Recording:
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise RecordingError("missing-manifest", "recording manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecordingError("invalid-manifest", "recording manifest is not JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise RecordingError("invalid-manifest", "recording manifest must be schemaVersion 1")
    recording_id = _check_id(str(manifest.get("recordingId", "")))
    sample_count = int(manifest["sampleCount"])
    channels_doc = manifest["channels"]
    if not isinstance(channels_doc, list) or not channels_doc:
        raise RecordingError("invalid-manifest", "recording needs at least one channel")
    channels = tuple(
        ChannelSpec(
            label=item["label"],
            reference=item["reference"],
            type=item["type"],
            unit=item["unit"],
        )
        for item in channels_doc
    )
    blob = np.fromfile(directory / SAMPLES_NAME, dtype="<f8")
    expected = len(channels) * sample_count
    if blob.size != expected:
        raise RecordingError("truncated-samples", "sample file length does not match the manifest")
    samples = np.ascontiguousarray(blob.reshape(len(channels), sample_count))
    digest = _sha256(samples)
    if digest != manifest.get("samplesSha256"):
        raise RecordingError("checksum-mismatch", "sample checksum does not match the manifest")
    provenance_doc = manifest["provenance"]
    if provenance_doc["kind"] == "synthetic":
        provenance: SyntheticProvenance | DeviceProvenance = SyntheticProvenance(
            generator=provenance_doc["generator"],
            generator_version=provenance_doc["generatorVersion"],
            seed=int(provenance_doc["seed"]),
            config_hash=provenance_doc["configHash"],
        )
    elif provenance_doc["kind"] == "device":
        provenance = DeviceProvenance()
    else:
        raise RecordingError("invalid-manifest", "unknown provenance kind")
    device_doc = manifest["device"]
    timestamp_source: TimestampSource = manifest["timestampSource"]
    descriptor = StreamDescriptor(
        device=DeviceInfo(
            kind=device_doc["kind"],
            model=device_doc["model"],
            device_id=device_doc["deviceId"],
            adapter_version=device_doc["adapterVersion"],
        ),
        channels=channels,
        nominal_sample_rate_hz=float(manifest["nominalSampleRateHz"]),
        timestamp_source=timestamp_source,
        provenance=provenance,
    )
    gaps = tuple(Gap(int(item["firstIndex"]), int(item["count"])) for item in manifest.get("gaps", []))
    present_runs(sample_count, gaps)
    return Recording(recording_id, samples, descriptor, gaps, directory)


def resolve_recording(root: Path, recording_id: str) -> Recording:
    recording_id = _check_id(recording_id)
    directory = (root / recording_id).resolve()
    if directory.parent != root.resolve():
        raise RecordingError("invalid-recording-id", "recording path escapes the recordings root")
    if not directory.is_dir():
        raise RecordingError("unknown-recording", f"no recording {recording_id}")
    return read_recording(directory)
