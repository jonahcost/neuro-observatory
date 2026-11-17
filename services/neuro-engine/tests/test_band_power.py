from __future__ import annotations

import math

import numpy as np

from neuro_engine.acquisition.base import ActiveStream, SampleBlock
from neuro_engine.acquisition.service import StreamBlock
from neuro_engine.analysis.band_power import (
    BandPowerAnalyzer,
    FindingStore,
    periodogram_power,
)
from neuro_engine.recordings.scenario import alpha_step_descriptor, alpha_step_samples


def _feed(samples: np.ndarray, *, rate: float = 125.0) -> FindingStore:
    _array, config, _step = alpha_step_samples(duration_s=1.0)
    descriptor = alpha_step_descriptor(config)
    descriptor = type(descriptor)(
        device=descriptor.device,
        channels=descriptor.channels,
        nominal_sample_rate_hz=rate,
        timestamp_source=descriptor.timestamp_source,
        provenance=descriptor.provenance,
    )
    store = FindingStore()
    analyzer = BandPowerAnalyzer(store)
    analyzer.set_context(1, "alpha-step")
    stream = ActiveStream("stream-a", descriptor, 0, 0)
    for start in range(0, samples.shape[1], 25):
        stop = min(samples.shape[1], start + 25)
        block = SampleBlock(start, start * int(1_000_000 / rate), samples[:, start:stop])
        analyzer.on_accepted(stream, StreamBlock("stream-a", start // 25, 0, block))
    return store


def test_bin_centered_alpha_power_is_near_the_sine() -> None:
    rate = 125.0
    count = int(rate * 2)
    tone = 20.0 * np.sin(2 * np.pi * 10.0 * np.arange(count) / rate)
    power = periodogram_power(tone, rate)["alpha"]
    assert math.isclose(power, 200.0, rel_tol=0.15)


def test_alpha_step_finding_cites_occipital_channels() -> None:
    samples, _config, step = alpha_step_samples()
    store = _feed(samples)
    findings = [item for item in store.findings if item.method == "band-power" and item.band == "alpha"]
    assert findings, "expected an alpha finding"
    finding = findings[0]
    labels = {channel.label for channel in finding.channels}
    assert {"O1", "O2"} <= labels
    assert finding.last_sample_index >= step
    assert all(channel.change_db >= 3 for channel in finding.channels if channel.label in {"O1", "O2"})
    assert "generated, not measured" in store.lines[0]
    wire = finding.to_wire()
    assert "samples" not in wire
    assert wire["channels"][0]["unit"] == "uV"


def test_flat_signal_does_not_qualify() -> None:
    samples, _config, _step = alpha_step_samples()
    store = _feed(np.zeros_like(samples))
    assert store.findings == [] or all(item.method != "band-power" for item in store.findings)
    # The analyzer evidence is not on the store. Re-run to read it.
    analyzer_store = FindingStore()
    from neuro_engine.analysis.band_power import BandPowerAnalyzer

    samples, config, _step = alpha_step_samples()
    descriptor = alpha_step_descriptor(config)
    analyzer = BandPowerAnalyzer(analyzer_store)
    stream = ActiveStream("flat", descriptor, 0, 0)
    zeros = np.zeros_like(samples)
    for start in range(0, zeros.shape[1], 25):
        stop = min(zeros.shape[1], start + 25)
        block = SampleBlock(start, start * 8000, zeros[:, start:stop])
        analyzer.on_accepted(stream, StreamBlock("flat", start, 0, block))
    assert analyzer.evidence == "insufficient"
    assert [item for item in analyzer_store.findings if item.method == "band-power"] == []


def test_large_gap_suppresses_the_finding() -> None:
    samples, config, _step = alpha_step_samples(duration_s=8.0, step_at_s=2.0)
    descriptor = alpha_step_descriptor(config)
    store = FindingStore()
    analyzer = BandPowerAnalyzer(store, baseline_s=2.0)
    stream = ActiveStream("gap", descriptor, 0, 0)
    # Deliver 2 s, then jump by more than 5% of the next 2 s window.
    first = samples[:, :250]
    analyzer.on_accepted(stream, StreamBlock("gap", 0, 0, SampleBlock(0, 0, first)))
    jumped = samples[:, 250:500]
    analyzer.on_accepted(stream, StreamBlock("gap", 1, 400, SampleBlock(650, 650 * 8000, jumped)))
    assert [item for item in store.findings if item.method == "band-power"] == []


def test_new_stream_clears_the_baseline_unless_kept() -> None:
    samples, config, _step = alpha_step_samples(duration_s=6.0, step_at_s=4.0)
    descriptor = alpha_step_descriptor(config)
    store = FindingStore()
    analyzer = BandPowerAnalyzer(store, baseline_s=2.0)
    first = ActiveStream("one", descriptor, 0, 0)
    for start in range(0, 500, 25):
        analyzer.on_accepted(first, StreamBlock("one", start, 0, SampleBlock(start, start * 8000, samples[:, start : start + 25])))
    assert analyzer._baseline is not None
    analyzer.prepare_restart(keep_baseline=False)
    second = ActiveStream("two", descriptor, 0, 0)
    analyzer.on_accepted(second, StreamBlock("two", 0, 0, SampleBlock(0, 0, samples[:, :25])))
    assert analyzer._baseline is None


def test_stale_health_suppresses_new_findings() -> None:
    samples, config, _step = alpha_step_samples()
    descriptor = alpha_step_descriptor(config)
    store = FindingStore()
    analyzer = BandPowerAnalyzer(store)
    analyzer.set_health_ok(False)
    stream = ActiveStream("stale", descriptor, 0, 0)
    for start in range(0, samples.shape[1], 25):
        stop = min(samples.shape[1], start + 25)
        analyzer.on_accepted(
            stream,
            StreamBlock("stale", start, 0, SampleBlock(start, start * 8000, samples[:, start:stop])),
        )
    assert [item for item in store.findings if item.method == "band-power"] == []
    assert analyzer.evidence == "stale"
