from __future__ import annotations

import asyncio
import dataclasses

import numpy as np
import pytest

from neuro_engine.acquisition.base import (
    DeviceDisconnectedError,
    SampleBlock,
    SyntheticProvenance,
)
from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.synthetic import (
    DEFAULT_CHANNEL_LABELS,
    DeviceConfigError,
    SyntheticConfig,
    SyntheticEegAdapter,
    SyntheticFault,
    generate_block,
)


async def collect(adapter: SyntheticEegAdapter, max_blocks: int) -> list[SampleBlock]:
    await adapter.open()
    blocks: list[SampleBlock] = []
    async for block in adapter.blocks():
        blocks.append(block)
        if len(blocks) >= max_blocks:
            break
    await adapter.close()
    return blocks


def run_blocks(config: SyntheticConfig, max_blocks: int, **kwargs: object) -> list[SampleBlock]:
    clock = VirtualClock()
    return asyncio.run(collect(SyntheticEegAdapter(config, clock, **kwargs), max_blocks))  # type: ignore[arg-type]


def test_default_configuration_is_16_channels_at_125_hz() -> None:
    config = SyntheticConfig()
    descriptor = config.descriptor()
    assert descriptor.channel_count == 16
    assert [c.label for c in descriptor.channels] == list(DEFAULT_CHANNEL_LABELS)
    assert descriptor.nominal_sample_rate_hz == 125.0
    assert all(c.unit == "uV" and c.type == "EEG" and c.reference == "synthetic" for c in descriptor.channels)
    assert descriptor.timestamp_source == "synthetic-nominal"
    assert isinstance(descriptor.provenance, SyntheticProvenance)
    assert descriptor.provenance.seed == config.seed
    assert descriptor.provenance.config_hash == config.config_hash()


def test_same_seed_is_bit_identical_and_different_seed_differs() -> None:
    a = generate_block(SyntheticConfig(seed=7), 3)
    b = generate_block(SyntheticConfig(seed=7), 3)
    c = generate_block(SyntheticConfig(seed=8), 3)
    assert a.shape == (16, 25)
    assert a.dtype == np.float64
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_adapter_output_equals_random_access_generation() -> None:
    config = SyntheticConfig(seed=3, block_size=10)
    blocks = run_blocks(config, 5)
    stitched = np.concatenate([b.data for b in blocks], axis=1)
    expected = np.concatenate([generate_block(config, n) for n in range(5)], axis=1)
    assert np.array_equal(stitched, expected)


def test_config_hash_changes_with_any_parameter() -> None:
    base = SyntheticConfig()
    assert base.config_hash() == SyntheticConfig().config_hash()
    assert base.config_hash() != dataclasses.replace(base, seed=1).config_hash()
    assert base.config_hash() != dataclasses.replace(base, noise_rms_uv=4.0).config_hash()


def test_spectrum_peaks_at_configured_alpha_and_theta() -> None:
    config = SyntheticConfig(seed=11)
    n_blocks = 50  # 1250 samples = 10 s at 125 Hz -> 0.1 Hz resolution
    data = np.concatenate([generate_block(config, n) for n in range(n_blocks)], axis=1)
    freqs = np.fft.rfftfreq(data.shape[1], d=1 / config.sample_rate_hz)
    for channel in (0, 8, 15):
        power = np.abs(np.fft.rfft(data[channel])) ** 2
        top_two = sorted(freqs[np.argsort(power)[-2:]])
        assert top_two == pytest.approx([6.0, 10.0])


def test_amplitude_is_physiologically_plausible_in_microvolts() -> None:
    data = np.concatenate([generate_block(SyntheticConfig(), n) for n in range(20)], axis=1)
    rms = np.sqrt(np.mean(data**2, axis=1))
    expected_rms = np.sqrt(20.0**2 / 2 + 6.0**2 / 2 + 5.0**2)
    assert np.all(np.abs(rms - expected_rms) < 2.0)
    assert np.max(np.abs(data)) < 100.0


def test_sample_indices_and_nominal_timestamps_are_contiguous() -> None:
    blocks = run_blocks(SyntheticConfig(block_size=25), 4)
    start_us = blocks[0].first_sample_time_us
    for n, block in enumerate(blocks):
        assert block.first_sample_index == n * 25
        assert block.sample_count == 25
        assert block.first_sample_time_us == start_us + n * 25 * 8_000  # 8 ms per sample at 125 Hz


def test_blocks_are_immutable() -> None:
    block = run_blocks(SyntheticConfig(), 1)[0]
    with pytest.raises(ValueError):
        block.data[0, 0] = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        block.first_sample_index = 5  # type: ignore[misc]


def test_drop_fault_omits_samples_without_fabricating_values() -> None:
    config = SyntheticConfig(block_size=10)
    blocks = run_blocks(config, 4, faults=[SyntheticFault("drop", at_sample=12, samples=5)])
    ranges = [(b.first_sample_index, b.first_sample_index + b.sample_count) for b in blocks]
    assert ranges[:3] == [(0, 10), (10, 12), (17, 20)]
    reference = generate_block(config, 1)
    assert np.array_equal(blocks[2].data, reference[:, 7:10])


def test_disconnect_fault_delivers_prior_samples_then_raises() -> None:
    adapter = SyntheticEegAdapter(SyntheticConfig(block_size=10), VirtualClock(), faults=[SyntheticFault("disconnect", at_sample=25)])

    async def scenario() -> list[SampleBlock]:
        await adapter.open()
        delivered: list[SampleBlock] = []
        with pytest.raises(DeviceDisconnectedError):
            async for block in adapter.blocks():
                delivered.append(block)
        return delivered

    delivered = asyncio.run(scenario())
    assert sum(b.sample_count for b in delivered) == 25
    assert delivered[-1].first_sample_index + delivered[-1].sample_count == 25


def test_adapter_is_single_use_and_requires_open() -> None:
    adapter = SyntheticEegAdapter(SyntheticConfig(), VirtualClock())

    async def scenario() -> None:
        with pytest.raises(RuntimeError):
            async for _ in adapter.blocks():
                pass
        await adapter.open()
        with pytest.raises(RuntimeError):
            await adapter.open()
        await adapter.close()
        await adapter.close()  # idempotent

    asyncio.run(scenario())
    assert adapter.closed


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed": -1},
        {"seed": True},
        {"sample_rate_hz": 0},
        {"sample_rate_hz": float("nan")},
        {"block_size": 0},
        {"channel_labels": ()},
        {"channel_labels": ("Cz", "Cz")},
        {"alpha_frequency_hz": 62.5},  # Nyquist at 125 Hz
        {"noise_rms_uv": -1.0},
    ],
)
def test_invalid_configuration_is_rejected(overrides: dict) -> None:
    with pytest.raises(DeviceConfigError):
        SyntheticConfig(**overrides)
