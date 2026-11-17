"""Cold and warm timings for the local analyzer. This does not download a model.

Renderer frame interval is not measured here; that needs a browser session.
When llama-server is not installed, model time-to-first-token is reported as unavailable.
"""

from __future__ import annotations

import json
import resource
import time

import numpy as np

from neuro_engine.acquisition.base import ActiveStream, SampleBlock
from neuro_engine.acquisition.clock import VirtualClock
from neuro_engine.acquisition.service import StreamBlock
from neuro_engine.analysis.band_power import (
    BandPowerAnalyzer,
    FindingStore,
    periodogram_power,
)
from neuro_engine.recordings.scenario import alpha_step_descriptor, alpha_step_samples


def _rss_bytes() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes. Linux reports kilobytes.
    if usage > 10_000_000:
        return int(usage)
    return int(usage * 1024)


def _feed(analyzer: BandPowerAnalyzer, samples: np.ndarray, descriptor) -> None:
    clock = VirtualClock()
    stream = ActiveStream(
        stream_id="bench",
        descriptor=descriptor,
        anchor_monotonic_us=clock.monotonic_us(),
        anchor_unix_time_us=clock.unix_time_us(),
    )
    analyzer.set_context(0, "alpha-step")
    block_size = 25
    for start in range(0, samples.shape[1], block_size):
        stop = min(samples.shape[1], start + block_size)
        data = samples[:, start:stop]
        block = SampleBlock(
            first_sample_index=start,
            first_sample_time_us=clock.monotonic_us(),
            data=data,
        )
        analyzer.on_accepted(
            stream,
            StreamBlock(stream_id="bench", block_sequence=start // block_size, dropped_samples_before=0, block=block),
        )


def run(repeats: int = 5) -> dict[str, object]:
    samples, config, _step = alpha_step_samples()
    descriptor = alpha_step_descriptor(config)
    rate = float(config.sample_rate_hz)
    cold_started = time.perf_counter()
    cold_store = FindingStore()
    cold = BandPowerAnalyzer(cold_store)
    _feed(cold, samples, descriptor)
    cold_s = time.perf_counter() - cold_started
    warm_times = []
    for _ in range(repeats):
        started = time.perf_counter()
        window = samples[0, : int(rate * 2)]
        periodogram_power(window, rate)
        warm_times.append(time.perf_counter() - started)
    warm_times.sort()
    p95_index = min(len(warm_times) - 1, max(0, round(0.95 * (len(warm_times) - 1))))
    return {
        "machine": "local",
        "channels": int(samples.shape[0]),
        "samples": int(samples.shape[1]),
        "coldAnalyzerSeconds": cold_s,
        "coldFindings": len(cold_store.findings),
        "warmPeriodogramSecondsP95": warm_times[p95_index],
        "warmPeriodogramRepeats": repeats,
        "rssBytes": _rss_bytes(),
        "model": "unavailable",
        "modelNote": "llama-server weights were not installed; time to first token was not measured.",
        "rendererNote": "requestAnimationFrame interval was not measured from this process.",
        "targets": {
            "analysisStepP95Seconds": 0.05,
            "warmTimeToFirstTokenSeconds": 1.5,
            "primaryRssBytes": 4_000_000_000,
            "frameIntervalP95Seconds": 0.034,
        },
    }


def main() -> None:
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
