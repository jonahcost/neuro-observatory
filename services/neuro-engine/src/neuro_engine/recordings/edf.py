"""Optional EDF import. Labels are preserved; nothing is renamed onto the synthetic montage.

MNE returns EEG in volts. This writer stores those rows as µV and omits every
other channel type. The protocol has no non-microvolt unit, so a stim channel
is not relabeled as µV. Engine timestamps during replay are the playback clock
(`host-receipt-fitted`), not the amplifier's original clock. EDF annotations
and discontinuities are not imported as gaps.
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


def eeg_channels_uv(
    names: list[str],
    types: list[str],
    volts: np.ndarray,
) -> tuple[np.ndarray, list[ChannelSpec]]:
    """Keep EEG rows and convert volts to µV.

    MNE returns EEG in volts. The protocol unit is µV, so stim and other
    non-EEG rows are omitted instead of being relabeled as microvolts.
    """
    if volts.ndim != 2 or volts.shape[0] != len(names) or len(names) != len(types):
        raise RecordingError("invalid-edf", "EDF channel names, types, and samples disagree")
    picks = [index for index, kind in enumerate(types) if kind == "eeg"]
    if not picks:
        return np.empty((0, volts.shape[1]), dtype=np.float64), []
    samples = np.ascontiguousarray(volts[picks] * 1e6, dtype=np.float64)
    channels = [ChannelSpec(label=names[index], reference="unknown", type="EEG") for index in picks]
    return samples, channels


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
    names = list(raw.ch_names)
    types = list(raw.get_channel_types())
    volts = np.ascontiguousarray(raw.get_data(), dtype=np.float64)
    samples, channels = eeg_channels_uv(names, types, volts)
    if samples.size == 0:
        raise RecordingError("no-eeg", "EDF import found no EEG channels to store in microvolts")
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
