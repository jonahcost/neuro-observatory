"""Deterministic synthetic recordings used by tests and the local demo.

These are generated signals. They are not measurements from a person.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from neuro_engine.acquisition.base import (
    ChannelSpec,
    DeviceInfo,
    StreamDescriptor,
    SyntheticProvenance,
)
from neuro_engine.acquisition.synthetic import SyntheticConfig
from neuro_engine.recordings.v1 import Recording, write_recording

SCENARIO_GENERATOR = "neuro_engine.recordings.scenario"
SCENARIO_VERSION = "1"


def _hash(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def alpha_step_samples(
    *,
    duration_s: float = 26.0,
    step_at_s: float = 20.0,
    low_uv: float = 20.0,
    high_uv: float = 60.0,
    noise_rms_uv: float = 5.0,
    seed: int = 1,
) -> tuple[np.ndarray, SyntheticConfig, int]:
    """Default 16-channel amplitudes, with O1 and O2 alpha stepping up after step_at_s.

    Seed 1 keeps this file distinct from the live synthetic adapter's seed 0 stream.
    """
    config = SyntheticConfig(seed=seed, noise_rms_uv=noise_rms_uv)
    rate = float(config.sample_rate_hz)
    count = int(duration_s * rate)
    step = int(step_at_s * rate)
    times = np.arange(count, dtype=np.float64) / rate
    phases = np.arange(len(config.channel_labels), dtype=np.float64) * config.channel_phase_step_rad
    data = np.zeros((len(config.channel_labels), count), dtype=np.float64)
    occipital = {label for label in ("O1", "O2") if label in config.channel_labels}
    for index, label in enumerate(config.channel_labels):
        alpha = np.full(count, low_uv, dtype=np.float64)
        if label in occipital:
            alpha[step:] = high_uv
        data[index] = alpha * np.sin(2 * np.pi * config.alpha_frequency_hz * times + phases[index])
        data[index] += config.theta_amplitude_uv * np.sin(
            2 * np.pi * config.theta_frequency_hz * times + 0.5 * phases[index]
        )
    rng = np.random.default_rng(seed)
    data += rng.normal(0.0, config.noise_rms_uv, size=data.shape)
    return data, config, step


def alpha_step_descriptor(config: SyntheticConfig) -> StreamDescriptor:
    payload = {
        "scenario": "alpha-step",
        "version": SCENARIO_VERSION,
        "seed": config.seed,
        "noise": config.noise_rms_uv,
        "labels": list(config.channel_labels),
    }
    return StreamDescriptor(
        device=DeviceInfo(
            kind="synthetic",
            model="neuro-observatory-synthetic-eeg",
            device_id="replay-alpha-step",
            adapter_version="1.0.0",
        ),
        channels=tuple(ChannelSpec(label=label, reference="synthetic") for label in config.channel_labels),
        nominal_sample_rate_hz=float(config.sample_rate_hz),
        timestamp_source="synthetic-nominal",
        provenance=SyntheticProvenance(
            generator=SCENARIO_GENERATOR,
            generator_version=SCENARIO_VERSION,
            seed=config.seed,
            config_hash=_hash(payload),
        ),
    )


def write_alpha_step(directory: Path, **kwargs: object) -> tuple[Recording, int]:
    duration_s = float(kwargs.get("duration_s", 26.0))
    step_at_s = float(kwargs.get("step_at_s", 20.0))
    samples, config, step = alpha_step_samples(duration_s=duration_s, step_at_s=step_at_s)
    recording = write_recording(
        directory,
        samples,
        alpha_step_descriptor(config),
        recording_id="alpha-step",
    )
    return recording, step
