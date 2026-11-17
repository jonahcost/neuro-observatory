"""Optional EDF import. Labels are preserved; nothing is renamed onto the synthetic montage.

MNE returns EEG in volts. This writer stores µV. Engine timestamps during replay
are the playback clock (`host-receipt-fitted`), not the amplifier's original clock.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from neuro_engine.acquisition.base import (
    ChannelSpec,
    DeviceInfo,
    DeviceProvenance,
    StreamDescriptor,
)
from neuro_engine.recordings.v1 import Recording, RecordingError, write_recording


def import_edf(source: Path, directory: Path, recording_id: str) -> Recording:
    try:
        import mne
    except ImportError as exc:
        raise RecordingError(
            "mne-missing",
            "EDF import needs the neuroimaging extra: uv sync --extra neuroimaging.",
        ) from exc
    if not source.is_file():
        raise RecordingError("missing-file", "EDF file was not found")
    raw = mne.io.read_raw_edf(source, preload=True, verbose="error")
    volts = np.ascontiguousarray(raw.get_data(), dtype=np.float64)
    samples = volts * 1e6
    channels = []
    for name, kind in zip(raw.ch_names, raw.get_channel_types(), strict=True):
        channel_type = "EEG" if kind == "eeg" else "MISC"
        channels.append(ChannelSpec(label=name, reference="unknown", type=channel_type))
    rate = float(raw.info["sfreq"])
    descriptor = StreamDescriptor(
        device=DeviceInfo(
            kind="replay",
            model="edf-import",
            device_id=recording_id,
            adapter_version="1.0.0",
        ),
        channels=tuple(channels),
        nominal_sample_rate_hz=rate,
        timestamp_source="host-receipt-fitted",
        provenance=DeviceProvenance(),
    )
    return write_recording(directory, samples, descriptor, recording_id=recording_id)
