"""Windowed scalp band power. This is not a cortical source estimate.

Band power is the sum of Hann-periodogram bins in µV². A relative change is
10*log10(power / baseline) in dB. Gaps are not filled with invented EEG: a
window missing more than 5% of its samples is rejected. A smaller gap is
replaced by the mean of the finite samples only inside this estimate, and the
accepted-sample fraction is stored on the finding.
"""

from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np

from neuro_engine.acquisition.base import ActiveStream, SyntheticProvenance
from neuro_engine.acquisition.service import AcquisitionService, StreamBlock
from neuro_engine.analysis.blink import blink_verdict, louder_occipital

METHOD = "band-power"
METHOD_VERSION = "1"
BANDS: dict[str, tuple[float, float]] = {
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
}
CHANGE_DB = 3.0
GAP_FRACTION = 0.05
RMS_HIGH_UV = 150.0
RMS_LOW_UV = 0.5
HISTORY_SECONDS = 60.0
NARRATE_SECONDS = 10.0


def periodogram_power(samples: np.ndarray, rate: float) -> dict[str, float]:
    """One-sided Hann periodogram power in µV² for each narrated band."""
    values = np.asarray(samples, dtype=np.float64)
    centered = values - np.mean(values)
    count = centered.shape[0]
    window = np.hanning(count)
    spectrum = np.fft.rfft(centered * window)
    # Energy-normalized one-sided periodogram. A bin-centered sine of amplitude
    # A sums to A²/2 µV² across the bins the Hann window spreads it over.
    power = (np.abs(spectrum) ** 2) / (float(np.sum(window**2)) * count)
    if count % 2 == 0:
        power[1:-1] *= 2.0
    else:
        power[1:] *= 2.0
    freqs = np.fft.rfftfreq(count, d=1.0 / rate)
    found: dict[str, float] = {}
    for name, (low, high) in BANDS.items():
        mask = (freqs >= low) & (freqs < high)
        found[name] = float(np.sum(power[mask]))
    return found


@dataclass(frozen=True, slots=True)
class ChannelMeasurement:
    index: int
    label: str
    reference: str
    unit: str
    power_uv2: float
    baseline_uv2: float
    change_db: float
    rms_uv: float
    accepted_sample_fraction: float
    quality: str


@dataclass(frozen=True, slots=True)
class Finding:
    finding_id: str
    session_generation: int
    stream_id: str
    recording_id: str | None
    source_kind: str
    device_id: str
    method: str
    method_version: str
    band: str
    first_sample_index: int
    last_sample_index: int
    first_sample_time_us: int
    last_sample_time_us: int
    nominal_sample_rate_hz: float
    channels: tuple[ChannelMeasurement, ...]
    quality: str
    synthetic: bool
    created_us: int

    def to_wire(self) -> dict[str, object]:
        return {
            "findingId": self.finding_id,
            "sessionGeneration": self.session_generation,
            "streamId": self.stream_id,
            "recordingId": self.recording_id,
            "sourceKind": self.source_kind,
            "deviceId": self.device_id,
            "method": self.method,
            "methodVersion": self.method_version,
            "band": self.band,
            "firstSampleIndex": self.first_sample_index,
            "lastSampleIndex": self.last_sample_index,
            "firstSampleTimeUs": self.first_sample_time_us,
            "lastSampleTimeUs": self.last_sample_time_us,
            "nominalSampleRateHz": self.nominal_sample_rate_hz,
            "channels": [
                {
                    "index": channel.index,
                    "label": channel.label,
                    "reference": channel.reference,
                    "unit": channel.unit,
                    "powerUv2": channel.power_uv2,
                    "baselineUv2": channel.baseline_uv2,
                    "changeDb": channel.change_db,
                    "rmsUv": channel.rms_uv,
                    "acceptedSampleFraction": channel.accepted_sample_fraction,
                    "quality": channel.quality,
                }
                for channel in self.channels
            ],
            "quality": self.quality,
            "synthetic": self.synthetic,
        }


@dataclass
class Marker:
    marker_id: str
    session_generation: int
    stream_id: str
    sample_index: int
    label: str

    def to_wire(self) -> dict[str, object]:
        return {
            "markerId": self.marker_id,
            "sessionGeneration": self.session_generation,
            "streamId": self.stream_id,
            "sampleIndex": self.sample_index,
            "label": self.label,
        }


@dataclass
class FindingStore:
    max_count: int = 200
    max_age_us: int = 30 * 60 * 1_000_000
    findings: deque[Finding] = field(default_factory=deque)
    markers: deque[Marker] = field(default_factory=deque)
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=20))

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        self._trim(finding.created_us)

    def mark_other_streams_stale(self, stream_id: str) -> None:
        """Findings from an older stream stay queryable and stop looking current."""
        kept: deque[Finding] = deque()
        for finding in self.findings:
            if finding.stream_id != stream_id and finding.quality == "good":
                kept.append(replace(finding, quality="stale"))
            else:
                kept.append(finding)
        self.findings = kept

    def add_line(self, line: str) -> None:
        self.lines.append(line)

    def add_marker(self, marker: Marker) -> None:
        self.markers.append(marker)
        while len(self.markers) > 100:
            self.markers.popleft()

    def _trim(self, now_us: int) -> None:
        while self.findings and (
            len(self.findings) > self.max_count or now_us - self.findings[0].created_us > self.max_age_us
        ):
            self.findings.popleft()

    def query(
        self,
        *,
        stream_id: str | None = None,
        generation: int | None = None,
        channel: str | None = None,
        band: str | None = None,
    ) -> list[Finding]:
        found: list[Finding] = []
        for finding in self.findings:
            if stream_id is not None and finding.stream_id != stream_id:
                continue
            if generation is not None and finding.session_generation != generation:
                continue
            if band is not None and finding.band != band:
                continue
            if channel is not None and all(item.label != channel for item in finding.channels):
                continue
            found.append(finding)
        return found


@dataclass
class _Hit:
    sign: int
    end_index: int


class _History:
    def __init__(self, channels: int, rate: float) -> None:
        self.rate = rate
        self.capacity = max(1, math.ceil(rate * HISTORY_SECONDS))
        self.values = np.full((channels, self.capacity), np.nan, dtype=np.float64)
        self.indexes = np.full(self.capacity, -1, dtype=np.int64)
        self.newest = -1
        self.expired = 0

    def append(self, data: np.ndarray, first_index: int) -> None:
        for offset in range(data.shape[1]):
            index = first_index + offset
            slot = index % self.capacity
            previous = int(self.indexes[slot])
            if previous >= 0 and previous != index:
                self.expired += 1
            self.values[:, slot] = data[:, offset]
            self.indexes[slot] = index
            self.newest = index

    def window(self, end_index: int, length: int) -> np.ndarray:
        start = end_index - length + 1
        out = np.empty((self.values.shape[0], length), dtype=np.float64)
        for offset, index in enumerate(range(start, end_index + 1)):
            slot = index % self.capacity
            if int(self.indexes[slot]) == index:
                out[:, offset] = self.values[:, slot]
            else:
                out[:, offset] = np.nan
        return out


def _prepare(samples: np.ndarray) -> tuple[np.ndarray, float, float, bool]:
    finite = np.isfinite(samples)
    fraction = float(np.mean(finite)) if samples.size else 0.0
    if fraction <= 0.0 or 1.0 - fraction > GAP_FRACTION:
        rms = float(np.sqrt(np.mean(samples[finite] ** 2))) if np.any(finite) else 0.0
        return samples, fraction, rms, False
    filled = samples.copy()
    if not np.all(finite):
        filled[~finite] = float(np.mean(samples[finite]))
    rms = float(np.sqrt(np.mean(filled**2)))
    if not math.isfinite(rms) or rms > RMS_HIGH_UV or rms < RMS_LOW_UV:
        return filled, fraction, rms, False
    return filled, fraction, rms, True


class BandPowerAnalyzer:
    def __init__(
        self,
        store: FindingStore,
        *,
        window_s: float = 2.0,
        step_s: float = 0.5,
        baseline_s: float = 20.0,
    ) -> None:
        self.store = store
        self.window_s = window_s
        self.step_s = step_s
        self.baseline_s = baseline_s
        self._history: _History | None = None
        self._stream: ActiveStream | None = None
        self._generation = 0
        self._recording_id: str | None = None
        self._keep_baseline = False
        self._baseline: dict[tuple[int, str], float] | None = None
        self._baseline_id = ""
        self._collect: dict[tuple[int, str], list[float]] = {}
        self._hits: dict[tuple[int, str], _Hit] = {}
        self._last_narrated: dict[str, int] = {}
        self._last_end: int | None = None
        self._accepted_windows = 0
        self._rejected_windows = 0
        self._evidence = "waiting"
        self._health_ok = True
        self._rate = 0.0
        self._window_n = 0
        self._step_n = 0
        self._baseline_n = 0
        self._anchor_index: int | None = None
        self._anchor_us = 0
        self._origin_index: int | None = None
        self._blinked_until = -1

    @property
    def evidence(self) -> str:
        if not self._health_ok and self._stream is not None and self._evidence == "ready":
            return "stale"
        return self._evidence

    @property
    def expired(self) -> int:
        return 0 if self._history is None else self._history.expired

    @property
    def stream_id(self) -> str | None:
        return None if self._stream is None else self._stream.stream_id

    @property
    def newest_index(self) -> int | None:
        if self._history is None or self._history.newest < 0:
            return None
        return int(self._history.newest)

    def set_health_ok(self, ok: bool) -> None:
        self._health_ok = ok

    def set_context(self, generation: int, recording_id: str | None) -> None:
        self._generation = generation
        self._recording_id = recording_id

    def prepare_restart(self, *, keep_baseline: bool) -> None:
        self._keep_baseline = keep_baseline

    def lock_baseline(self) -> bool:
        if not self._collect:
            return False
        self._baseline = {key: float(np.median(values)) for key, values in self._collect.items() if values}
        self._baseline_id = uuid.uuid4().hex
        self._evidence = "ready" if self._baseline else "insufficient"
        return bool(self._baseline)

    def on_accepted(self, stream: ActiveStream, block: StreamBlock) -> None:
        if self._stream is None or self._stream.stream_id != stream.stream_id:
            if self._stream is not None:
                self.store.mark_other_streams_stale(stream.stream_id)
            kept = self._baseline if self._keep_baseline else None
            self._reset(stream)
            if kept:
                self._baseline = kept
                self._evidence = "ready"
            self._keep_baseline = False
        assert self._history is not None
        if self._anchor_index is None:
            self._anchor_index = block.block.first_sample_index
            self._anchor_us = block.block.first_sample_time_us
            self._origin_index = block.block.first_sample_index
        self._history.append(block.block.data, block.block.first_sample_index)
        self._drain()

    def _reset(self, stream: ActiveStream) -> None:
        self._stream = stream
        self._rate = float(stream.descriptor.nominal_sample_rate_hz)
        self._window_n = max(8, round(self.window_s * self._rate))
        self._step_n = max(1, round(self.step_s * self._rate))
        self._baseline_n = max(self._window_n, round(self.baseline_s * self._rate))
        self._history = _History(stream.descriptor.channel_count, self._rate)
        self._baseline = None
        self._collect = {}
        self._hits = {}
        self._last_narrated = {}
        self._last_end = None
        self._accepted_windows = 0
        self._rejected_windows = 0
        self._anchor_index = None
        self._anchor_us = 0
        self._origin_index = None
        self._blinked_until = -1
        self._evidence = "warming"

    def _drain(self) -> None:
        history = self._history
        if history is None or history.newest < 0:
            return
        origin = self._origin_index
        if origin is None or history.newest < origin:
            return
        if history.newest - origin + 1 < self._window_n:
            self._evidence = "warming"
            return
        first_end = origin + self._window_n - 1
        end = first_end if self._last_end is None else self._last_end + self._step_n
        if history.newest - end > self._step_n * 8:
            end = first_end + ((history.newest - first_end) // self._step_n) * self._step_n
        while end <= history.newest:
            self._evaluate(end)
            self._last_end = end
            end += self._step_n

    def _evaluate(self, end_index: int) -> None:
        stream = self._stream
        history = self._history
        if stream is None or history is None:
            return
        window = history.window(end_index, self._window_n)
        any_good = False
        powers: dict[tuple[int, str], tuple[float, float, float]] = {}
        for channel in range(window.shape[0]):
            filled, fraction, rms, ok = _prepare(window[channel])
            if not ok:
                continue
            any_good = True
            for band, power in periodogram_power(filled, self._rate).items():
                powers[(channel, band)] = (power, rms, fraction)
        if any_good:
            self._accepted_windows += 1
        else:
            self._rejected_windows += 1
        if self._health_ok:
            self._maybe_blink(stream, end_index, window)
        origin = 0 if self._origin_index is None else self._origin_index
        if self._baseline is None and end_index - origin < self._baseline_n:
            for key, (power, _, _) in powers.items():
                self._collect.setdefault(key, []).append(power)
            self._evidence = "baseline-unlocked" if any_good else "insufficient"
            return
        if self._baseline is None:
            if self._collect and any(self._collect.values()):
                self.lock_baseline()
            else:
                self._evidence = "insufficient"
                return
        if not self._health_ok:
            self._evidence = "stale"
            return
        confirmed: dict[tuple[str, int], list[ChannelMeasurement]] = {}
        labels = stream.descriptor.channels
        refreshed: set[tuple[int, str]] = set()
        for key, (power, rms, fraction) in powers.items():
            baseline = None if self._baseline is None else self._baseline.get(key)
            if baseline is None or baseline <= 1e-6 or power <= 0:
                self._hits.pop(key, None)
                continue
            change = 10.0 * math.log10(power / baseline)
            if not math.isfinite(change) or abs(change) < CHANGE_DB:
                self._hits.pop(key, None)
                continue
            sign = 1 if change > 0 else -1
            previous = self._hits.get(key)
            self._hits[key] = _Hit(sign, end_index)
            refreshed.add(key)
            if previous is None or previous.sign != sign or previous.end_index >= end_index:
                continue
            channel, band = key
            spec = labels[channel]
            confirmed.setdefault((band, sign), []).append(
                ChannelMeasurement(
                    index=channel,
                    label=spec.label,
                    reference=spec.reference,
                    unit=spec.unit,
                    power_uv2=power,
                    baseline_uv2=baseline,
                    change_db=change,
                    rms_uv=rms,
                    accepted_sample_fraction=fraction,
                    quality="good",
                )
            )
        for key in list(self._hits):
            if key not in refreshed:
                self._hits.pop(key, None)
        self._evidence = "ready"
        for (band, _sign), channels in confirmed.items():
            previous_end = self._last_narrated.get(band, -(10**9))
            if end_index - previous_end < int(NARRATE_SECONDS * self._rate):
                continue
            self._emit(stream, end_index, band, tuple(channels))
            self._last_narrated[band] = end_index

    def _emit(self, stream: ActiveStream, end_index: int, band: str, channels: tuple[ChannelMeasurement, ...]) -> None:
        start = end_index - self._window_n + 1
        synthetic = isinstance(stream.descriptor.provenance, SyntheticProvenance)
        finding = Finding(
            finding_id=uuid.uuid4().hex,
            session_generation=self._generation,
            stream_id=stream.stream_id,
            recording_id=self._recording_id,
            source_kind="synthetic" if synthetic else "device",
            device_id=stream.descriptor.device.device_id,
            method=METHOD,
            method_version=METHOD_VERSION,
            band=band,
            first_sample_index=start,
            last_sample_index=end_index,
            first_sample_time_us=self._time_us(start),
            last_sample_time_us=self._time_us(end_index),
            nominal_sample_rate_hz=self._rate,
            channels=channels,
            quality="good",
            synthetic=synthetic,
            created_us=self._time_us(end_index),
        )
        self.store.add(finding)
        self.store.add_line(finding_sentence(finding))

    def _time_us(self, index: int) -> int:
        if self._anchor_index is None:
            return 0
        period = 1_000_000 / self._rate if self._rate else 0.0
        return int(self._anchor_us + round((index - self._anchor_index) * period))

    def _maybe_blink(self, stream: ActiveStream, end_index: int, window: np.ndarray) -> None:
        labels = [channel.label for channel in stream.descriptor.channels]
        if "Fp1" not in labels or "Fp2" not in labels:
            return
        look = min(window.shape[1], max(1, round(self._rate)))
        recent = window[:, -look:]
        fp1 = recent[labels.index("Fp1")]
        fp2 = recent[labels.index("Fp2")]
        occipital_rows = [recent[labels.index(label)] for label in ("O1", "O2") if label in labels]
        occipital = louder_occipital(occipital_rows)
        verdict = blink_verdict(fp1, fp2, occipital, self._rate)
        if verdict != "blink" or end_index < self._blinked_until:
            return
        self._blinked_until = end_index + int(self._rate)
        start = end_index - look + 1
        peak = float(max(np.max(np.abs(fp1)), np.max(np.abs(fp2))))
        synthetic = isinstance(stream.descriptor.provenance, SyntheticProvenance)
        channels = []
        for label in ("Fp1", "Fp2"):
            index = labels.index(label)
            spec = stream.descriptor.channels[index]
            channels.append(
                ChannelMeasurement(
                    index=index,
                    label=label,
                    reference=spec.reference,
                    unit=spec.unit,
                    power_uv2=0.0,
                    baseline_uv2=0.0,
                    change_db=0.0,
                    rms_uv=peak,
                    accepted_sample_fraction=1.0,
                    quality="good",
                )
            )
        finding = Finding(
            finding_id=uuid.uuid4().hex,
            session_generation=self._generation,
            stream_id=stream.stream_id,
            recording_id=self._recording_id,
            source_kind="synthetic" if synthetic else "device",
            device_id=stream.descriptor.device.device_id,
            method="blink-heuristic",
            method_version="1",
            band="none",
            first_sample_index=start,
            last_sample_index=end_index,
            first_sample_time_us=self._time_us(start),
            last_sample_time_us=self._time_us(end_index),
            nominal_sample_rate_hz=self._rate,
            channels=tuple(channels),
            quality="good",
            synthetic=synthetic,
            created_us=self._time_us(end_index),
        )
        self.store.add(finding)
        sentence = (
            f"Likely blink on Fp1 and Fp2 (peak {peak:.0f} µV, samples {start}–{end_index}). "
            "This is a scalp artifact heuristic, not a source estimate."
        )
        if synthetic:
            sentence += " Synthetic signal — generated, not measured from a person."
        self.store.add_line(sentence)


def finding_sentence(finding: Finding) -> str:
    """Template narration. The model does not write this sentence."""
    names = ", ".join(channel.label for channel in finding.channels)
    detail = ", ".join(f"{channel.label} {channel.change_db:+.1f} dB" for channel in finding.channels)
    sentence = (
        f"{names} {finding.band} power changed: {detail}, "
        f"over samples {finding.first_sample_index}–{finding.last_sample_index}."
    )
    if any(channel.accepted_sample_fraction < 1.0 for channel in finding.channels):
        sentence += " Missing samples were replaced by the window mean inside this estimate only."
    if finding.synthetic:
        sentence += " Synthetic signal — generated, not measured from a person."
    return sentence


def observe_acquisition_health(service: AcquisitionService, analyzer: BandPowerAnalyzer) -> None:
    """Close the analyzer's health gate from the acquisition service's own reasons."""

    def listener(stream: ActiveStream, block: StreamBlock) -> None:
        reasons = service.health().reasons
        analyzer.set_health_ok("no-recent-data" not in reasons and "not-streaming" not in reasons)
        analyzer.on_accepted(stream, block)

    service.add_accepted_listener(listener)
