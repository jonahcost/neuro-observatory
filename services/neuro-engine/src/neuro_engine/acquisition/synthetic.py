"""Deterministic synthetic EEG source.

The output is software-generated and labelled synthetic end-to-end. It is a
function of (configuration, seed, block number) only, so tests and replays are
bit-reproducible for a given NumPy version.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np

from neuro_engine.acquisition.base import (
    ChannelSpec,
    DeviceConfigError,
    DeviceDisconnectedError,
    DeviceInfo,
    SampleBlock,
    StreamDescriptor,
    SyntheticProvenance,
)
from neuro_engine.acquisition.clock import Clock

GENERATOR = "neuro_engine.acquisition.synthetic"
GENERATOR_VERSION = "1"
ADAPTER_VERSION = "1.0.0"
MAX_SEED = 2**53 - 1

DEFAULT_CHANNEL_LABELS: tuple[str, ...] = (
    "Fp1", "Fp2", "F3", "F4", "F7", "F8",
    "C3", "C4", "Cz", "P3", "P4",
    "T7", "T8", "O1", "O2", "Pz",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class SyntheticConfig:
    seed: int = 0
    sample_rate_hz: float = 125.0
    block_size: int = 25
    channel_labels: tuple[str, ...] = DEFAULT_CHANNEL_LABELS
    alpha_amplitude_uv: float = 20.0
    alpha_frequency_hz: float = 10.0
    theta_amplitude_uv: float = 6.0
    theta_frequency_hz: float = 6.0
    noise_rms_uv: float = 5.0
    channel_phase_step_rad: float = 0.2

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or not 0 <= self.seed <= MAX_SEED:
            raise DeviceConfigError(f"seed must be an integer in [0, {MAX_SEED}]")
        if not math.isfinite(self.sample_rate_hz) or not 0 < self.sample_rate_hz <= 100_000:
            raise DeviceConfigError("sample_rate_hz must be in (0, 100000]")
        if isinstance(self.block_size, bool) or not isinstance(self.block_size, int) or not 1 <= self.block_size <= 10_000:
            raise DeviceConfigError("block_size must be an integer in [1, 10000]")
        if not 1 <= len(self.channel_labels) <= 1024:
            raise DeviceConfigError("channel_labels must contain 1 to 1024 labels")
        if len(set(self.channel_labels)) != len(self.channel_labels) or any(not 1 <= len(label) <= 64 for label in self.channel_labels):
            raise DeviceConfigError("channel_labels must be unique and 1-64 characters")
        nyquist = self.sample_rate_hz / 2
        for name in ("alpha_frequency_hz", "theta_frequency_hz"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 < value < nyquist:
                raise DeviceConfigError(f"{name} must be in (0, {nyquist}) Hz to avoid aliasing")
        for name in ("alpha_amplitude_uv", "theta_amplitude_uv", "noise_rms_uv", "channel_phase_step_rad"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise DeviceConfigError(f"{name} must be finite and non-negative")

    def config_hash(self) -> str:
        canonical = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()

    def descriptor(self, device_id: str = "synthetic-0") -> StreamDescriptor:
        return StreamDescriptor(
            device=DeviceInfo(
                kind="synthetic",
                model="neuro-observatory-synthetic-eeg",
                device_id=device_id,
                adapter_version=ADAPTER_VERSION,
            ),
            channels=tuple(ChannelSpec(label=label, reference="synthetic") for label in self.channel_labels),
            nominal_sample_rate_hz=float(self.sample_rate_hz),
            timestamp_source="synthetic-nominal",
            provenance=SyntheticProvenance(
                generator=GENERATOR,
                generator_version=GENERATOR_VERSION,
                seed=self.seed,
                config_hash=self.config_hash(),
            ),
        )


def generate_block(config: SyntheticConfig, block_number: int) -> np.ndarray:
    """Samples [block_number * block_size, (block_number + 1) * block_size) in µV.

    Shape (channels, block_size). Sinusoids are exact functions of the sample
    index; noise is drawn from a generator keyed by (seed, block_number).
    """
    if block_number < 0:
        raise ValueError("block_number must be non-negative")
    start = block_number * config.block_size
    t = np.arange(start, start + config.block_size, dtype=np.float64) / config.sample_rate_hz
    phases = np.arange(len(config.channel_labels), dtype=np.float64)[:, None] * config.channel_phase_step_rad
    signal = config.alpha_amplitude_uv * np.sin(2 * np.pi * config.alpha_frequency_hz * t + phases)
    signal += config.theta_amplitude_uv * np.sin(2 * np.pi * config.theta_frequency_hz * t + 0.5 * phases)
    rng = np.random.default_rng([config.seed, block_number])
    signal += rng.normal(0.0, config.noise_rms_uv, size=signal.shape)
    return signal


@dataclass(frozen=True, slots=True)
class SyntheticFault:
    """Scripted failure for tests.

    `drop`: samples [at_sample, at_sample + samples) are never delivered.
    `disconnect`: samples before `at_sample` are delivered, then the adapter
    raises DeviceDisconnectedError.
    """

    kind: Literal["drop", "disconnect"]
    at_sample: int
    samples: int = 0

    def __post_init__(self) -> None:
        if self.at_sample < 0:
            raise DeviceConfigError("fault at_sample must be non-negative")
        if self.kind == "drop" and self.samples < 1:
            raise DeviceConfigError("drop fault needs samples >= 1")


class SyntheticEegAdapter:
    """DeviceAdapter producing deterministic synthetic EEG paced by a Clock.

    A block is released when its last sample would have been acquired, using
    absolute deadlines from the stream start so pacing never accumulates drift.
    """

    def __init__(
        self,
        config: SyntheticConfig,
        clock: Clock,
        *,
        faults: Sequence[SyntheticFault] = (),
        device_id: str = "synthetic-0",
    ) -> None:
        self._config = config
        self._clock = clock
        self._descriptor = config.descriptor(device_id)
        self._drops = [(f.at_sample, f.at_sample + f.samples) for f in faults if f.kind == "drop"]
        disconnects = [f.at_sample for f in faults if f.kind == "disconnect"]
        self._disconnect_at = min(disconnects) if disconnects else None
        self._opened = False
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def open(self) -> StreamDescriptor:
        if self._opened or self._closed:
            raise RuntimeError("SyntheticEegAdapter is single-use")
        self._opened = True
        return self._descriptor

    def _is_dropped(self, index: int) -> bool:
        return any(lo <= index < hi for lo, hi in self._drops)

    def _runs(self, first: int, last_exclusive: int) -> list[tuple[int, int]]:
        """Contiguous delivered index ranges within [first, last_exclusive)."""
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for index in range(first, last_exclusive):
            if self._is_dropped(index):
                if start is not None:
                    runs.append((start, index))
                    start = None
            elif start is None:
                start = index
        if start is not None:
            runs.append((start, last_exclusive))
        return runs

    async def blocks(self) -> AsyncIterator[SampleBlock]:
        if not self._opened:
            raise RuntimeError("open() must be called before blocks()")
        cfg = self._config
        period_us = 1_000_000 / cfg.sample_rate_hz
        start_us = self._clock.monotonic_us()
        block_number = 0
        while not self._closed:
            first = block_number * cfg.block_size
            end = first + cfg.block_size
            disconnecting = self._disconnect_at is not None and self._disconnect_at < end
            if disconnecting:
                end = max(first, self._disconnect_at or 0)
            await self._clock.sleep_until(start_us + round(end * period_us))
            if self._closed:
                return
            data = generate_block(cfg, block_number)
            for lo, hi in self._runs(first, end):
                yield SampleBlock(
                    first_sample_index=lo,
                    first_sample_time_us=start_us + round(lo * period_us),
                    data=data[:, lo - first : hi - first],
                )
            if disconnecting:
                raise DeviceDisconnectedError("synthetic disconnect fault")
            block_number += 1

    async def close(self) -> None:
        self._closed = True
