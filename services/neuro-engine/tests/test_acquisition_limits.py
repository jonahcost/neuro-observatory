"""Acquisition-boundary limits must equal the canonical protocol schema."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest
from conftest import SCHEMA_PATH

from neuro_engine.acquisition import base
from neuro_engine.acquisition.base import (
    ChannelSpec,
    DeviceConfigError,
    DeviceInfo,
    StreamDescriptor,
    SyntheticProvenance,
)
from neuro_engine.acquisition.synthetic import SyntheticConfig

DEFS = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]


def _anchored(pattern: str) -> str:
    assert pattern.startswith("^") and pattern.endswith("$")
    return pattern[1:-1]


def test_limits_match_the_canonical_schema() -> None:
    block = DEFS["EegBlock"]["properties"]
    metadata = DEFS["StreamMetadata"]["properties"]
    channel = DEFS["ChannelSpec"]["properties"]
    assert base.MAX_SAFE_INTEGER == DEFS["Counter"]["maximum"] == DEFS["MonotonicMicroseconds"]["maximum"]
    assert base.MAX_CHANNELS == metadata["channels"]["maxItems"] == block["samples"]["maxItems"]
    assert base.MAX_BLOCK_SAMPLES == block["sampleCount"]["maximum"] == block["samples"]["items"]["maxItems"]
    assert base.MAX_SAMPLE_RATE_HZ == metadata["nominalSampleRateHz"]["maximum"]
    assert base.MAX_LABEL_LENGTH == channel["label"]["maxLength"]
    assert base.MAX_TEXT_LENGTH == DEFS["ShortText"]["maxLength"]
    assert base.SLUG_PATTERN.pattern == _anchored(DEFS["DeviceInfo"]["properties"]["kind"]["pattern"])
    assert base.CONFIG_HASH_PATTERN.pattern == _anchored(DEFS["SyntheticProvenance"]["properties"]["configHash"]["pattern"])
    assert base.CHANNEL_TYPES == set(channel["type"]["enum"])
    assert base.SIGNAL_UNITS == set(channel["unit"]["enum"])
    assert base.TIMESTAMP_SOURCES == set(DEFS["Timebase"]["properties"]["timestampSource"]["enum"])


VALID = SyntheticConfig(channel_labels=("C3", "C4")).descriptor()


def _device(**changes: Any) -> Callable[[], object]:
    return lambda: dataclasses.replace(VALID.device, **changes)


def _channel(**changes: Any) -> Callable[[], object]:
    return lambda: dataclasses.replace(VALID.channels[0], **changes)


def _provenance(**changes: Any) -> Callable[[], object]:
    assert isinstance(VALID.provenance, SyntheticProvenance)
    provenance = VALID.provenance
    return lambda: dataclasses.replace(provenance, **changes)


def _descriptor(**changes: Any) -> Callable[[], object]:
    return lambda: dataclasses.replace(VALID, **changes)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(_device(kind="OpenBCI"), id="device-kind-not-kebab-case"),
        pytest.param(_device(kind=""), id="device-kind-empty"),
        pytest.param(_device(model=""), id="device-model-empty"),
        pytest.param(_device(device_id="x" * 129), id="device-id-too-long"),
        pytest.param(_device(adapter_version=""), id="adapter-version-empty"),
        pytest.param(_device(firmware_version=""), id="firmware-version-empty"),
        pytest.param(_channel(label="x" * 65), id="label-too-long"),
        pytest.param(_channel(reference=""), id="reference-empty"),
        pytest.param(_channel(type="EKG"), id="unknown-channel-type"),
        pytest.param(_channel(unit="mV"), id="unsupported-unit"),
        pytest.param(_provenance(seed=-1), id="negative-seed"),
        pytest.param(_provenance(seed=True), id="boolean-seed"),
        pytest.param(_provenance(config_hash="md5:abc"), id="bad-config-hash"),
        pytest.param(_descriptor(channels=()), id="no-channels"),
        pytest.param(
            _descriptor(channels=tuple(ChannelSpec(f"E{i}", "ref") for i in range(1025))), id="too-many-channels"
        ),
        pytest.param(_descriptor(nominal_sample_rate_hz=0.0), id="zero-rate"),
        pytest.param(_descriptor(nominal_sample_rate_hz=100_001.0), id="rate-above-limit"),
        pytest.param(_descriptor(nominal_sample_rate_hz=float("nan")), id="nan-rate"),
        pytest.param(_descriptor(timestamp_source="wall-clock"), id="unknown-timestamp-source"),
    ],
)
def test_descriptors_outside_protocol_limits_are_config_errors(build: Callable[[], object]) -> None:
    with pytest.raises(DeviceConfigError):
        build()


def test_limit_values_themselves_are_accepted() -> None:
    StreamDescriptor(
        device=DeviceInfo("a" * 64, "m" * 128, "d" * 128, "v" * 128, "f" * 128),
        channels=tuple(ChannelSpec(f"{i:064d}", "r" * 128, "MISC") for i in range(1024)),
        nominal_sample_rate_hz=100_000,
        timestamp_source="device-clock",
        provenance=VALID.provenance,
    )
