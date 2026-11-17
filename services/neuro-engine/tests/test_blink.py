from __future__ import annotations

import numpy as np

from neuro_engine.acquisition.base import ActiveStream, SampleBlock
from neuro_engine.acquisition.service import StreamBlock
from neuro_engine.analysis.band_power import BandPowerAnalyzer, FindingStore
from neuro_engine.analysis.blink import (
    CLASSIFIER_ENABLED,
    blink_verdict,
    load_classifier,
    louder_occipital,
)
from neuro_engine.recordings.scenario import alpha_step_descriptor, alpha_step_samples


def test_classifier_stays_disabled() -> None:
    assert CLASSIFIER_ENABLED is False
    assert load_classifier() is None


def test_blink_heuristic_positive_negative_and_too_long() -> None:
    rate = 125.0
    count = int(rate)  # 1 s
    quiet = np.zeros(count)
    fp1 = quiet.copy()
    fp2 = quiet.copy()
    fp1[10:35] = 150
    fp2[10:35] = 140
    assert blink_verdict(fp1, fp2, quiet, rate) == "blink"
    assert blink_verdict(fp1, quiet, quiet, rate) == "none"
    long_a = np.full(int(rate), 150.0)
    long_b = np.full(int(rate), 140.0)
    assert blink_verdict(long_a, long_b, quiet, rate) == "too-long"
    occipital = np.full(count, 200.0)
    assert blink_verdict(fp1, fp2, occipital, rate) == "none"
    opposite = np.zeros(count)
    opposite[10:35] = -400
    small = np.full(count, 20.0)
    louder = louder_occipital([small, opposite])
    assert louder is opposite
    assert blink_verdict(fp1, fp2, louder, rate) == "none"


def test_analyzer_emits_one_blink_finding_for_a_frontal_burst() -> None:
    samples, config, _step = alpha_step_samples(duration_s=4.0, step_at_s=3.0)
    labels = list(config.channel_labels)
    burst = samples.copy()
    start = 125
    burst[labels.index("Fp1"), start : start + 25] += 180
    burst[labels.index("Fp2"), start : start + 25] += 170
    descriptor = alpha_step_descriptor(config)
    store = FindingStore()
    analyzer = BandPowerAnalyzer(store, baseline_s=2.0)
    stream = ActiveStream("blink", descriptor, 0, 0)
    for offset in range(0, burst.shape[1], 25):
        analyzer.on_accepted(
            stream,
            StreamBlock("blink", offset, 0, SampleBlock(offset, offset * 8000, burst[:, offset : offset + 25])),
        )
    blinks = [item for item in store.findings if item.method == "blink-heuristic"]
    assert len(blinks) == 1
    assert {channel.label for channel in blinks[0].channels} == {"Fp1", "Fp2"}
    assert any("heuristic" in line for line in store.lines)
