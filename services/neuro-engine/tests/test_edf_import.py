from __future__ import annotations

import numpy as np

from neuro_engine.recordings.edf import eeg_channels_uv


def test_edf_import_keeps_eeg_microvolts_and_drops_stim() -> None:
    volts = np.array([[1e-6, 2e-6], [5.0, 5.0]], dtype=np.float64)
    samples, channels = eeg_channels_uv(["Fp1", "STI 014"], ["eeg", "stim"], volts)
    assert samples.shape == (1, 2)
    assert np.allclose(samples[0], [1.0, 2.0])
    assert [channel.label for channel in channels] == ["Fp1"]
    assert channels[0].unit == "uV"
    assert channels[0].type == "EEG"
    assert channels[0].reference == "unknown"
