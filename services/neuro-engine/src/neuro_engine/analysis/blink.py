"""Frontal blink heuristic. Not a diagnosis and not a source estimate.

The classifier loader is intentionally disabled until a held-out comparison
beats this heuristic (ADR-0018).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

CLASSIFIER_ENABLED = False
PEAK_UV = 80.0
FLOOR_UV = 40.0
MIN_SECONDS = 0.05
MAX_SECONDS = 0.5
MIN_CORRELATION = 0.6


def load_classifier(_path: Path | None = None) -> None:
    """No classifier is loaded. A later ADR has to enable one."""
    return


def blink_verdict(
    fp1: np.ndarray,
    fp2: np.ndarray,
    occipital: np.ndarray | None,
    rate: float,
) -> str:
    """Return `blink`, `too-long`, or `none` for one contiguous candidate."""
    if fp1.shape != fp2.shape or fp1.size < 2 or rate <= 0:
        return "none"
    duration = fp1.shape[0] / rate
    hot = (np.abs(fp1) >= FLOOR_UV) & (np.abs(fp2) >= FLOOR_UV)
    longest = _longest(hot)
    burst_s = longest / rate
    if duration > MAX_SECONDS and burst_s > MAX_SECONDS:
        return "too-long"
    if burst_s > MAX_SECONDS:
        return "too-long"
    if burst_s < MIN_SECONDS:
        return "none"
    if float(np.max(np.abs(fp1))) < PEAK_UV or float(np.max(np.abs(fp2))) < PEAK_UV:
        return "none"
    if not np.all(np.isfinite(fp1)) or not np.all(np.isfinite(fp2)):
        return "none"
    correlation = float(np.corrcoef(fp1, fp2)[0, 1])
    if not np.isfinite(correlation) or correlation < MIN_CORRELATION:
        return "none"
    frontal = float(np.sqrt(np.mean(np.maximum(fp1, fp2) ** 2)))
    if occipital is not None and occipital.size == fp1.size:
        occipital_rms = float(np.sqrt(np.mean(occipital**2)))
        if frontal > 0 and occipital_rms > 0.5 * frontal:
            return "none"
    return "blink"


def _longest(flags: np.ndarray) -> int:
    best = 0
    current = 0
    for flag in flags:
        if bool(flag):
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best
