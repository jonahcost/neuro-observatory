"""Assistant contract v1 models mirroring packages/protocol/schemas/assistant.v1.schema.json.

The JSON Schema is canonical. Findings store summaries, not raw samples (ADR-0016).
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
)
from pydantic.alias_generators import to_camel

from neuro_engine.protocol.v2 import (
    Counter,
    JsonInteger,
    ProtocolError,
    ShortText,
    decode_json,
)

SCHEMA_VERSION: Literal[1] = 1
Line = Annotated[str, StringConstraints(min_length=1, max_length=400)]
OptionalId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Fraction = Annotated[float, Field(ge=0, le=1)]
Quality = Literal["good", "insufficient", "stale"]
DisplayMode = Literal["pial", "white", "inflated", "holographic", "grid"]


class _Doc(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        allow_inf_nan=True,
    )


class ChannelMeasurement(_Doc):
    index: Counter
    label: ShortText
    reference: ShortText
    unit: Literal["uV"]
    power_uv2: float
    baseline_uv2: float
    change_db: float
    rms_uv: float
    accepted_sample_fraction: Fraction
    quality: Quality


class Finding(_Doc):
    finding_id: ShortText
    session_generation: Counter
    stream_id: ShortText
    recording_id: OptionalId | None
    source_kind: Literal["synthetic", "device"]
    device_id: ShortText
    method: Literal["band-power", "blink-heuristic"]
    method_version: Literal["1"]
    band: Literal["theta", "alpha", "beta", "none"]
    first_sample_index: Counter
    last_sample_index: Counter
    first_sample_time_us: Counter
    last_sample_time_us: Counter
    nominal_sample_rate_hz: Annotated[float, Field(gt=0)]
    channels: Annotated[list[ChannelMeasurement], Field(min_length=1, max_length=64)]
    quality: Quality
    synthetic: bool


class Marker(_Doc):
    marker_id: ShortText
    session_generation: Counter
    stream_id: ShortText
    sample_index: Counter
    label: ShortText


class AssistantSnapshot(_Doc):
    type: Literal["assistant.snapshot"]
    schema_version: Literal[1]
    session_generation: Counter
    stream_id: str | None
    source: Literal["synthetic", "replay"]
    recording_id: str | None
    paused: bool
    evidence: Literal["waiting", "warming", "baseline-unlocked", "ready", "insufficient", "stale"]
    model: Literal["unavailable", "ready", "starting"]
    classifier: Literal["disabled"]
    analysis_samples_expired: Counter
    findings: Annotated[list[Finding], Field(max_length=200)]
    markers: Annotated[list[Marker], Field(max_length=100)]
    lines: Annotated[list[Line], Field(max_length=20)]


class IntentResult(_Doc):
    type: Literal["assistant.intent-result"]
    schema_version: Literal[1]
    ok: bool
    intent: Literal[
        "emphasize_channels",
        "seek_to_finding",
        "add_marker",
        "lock_baseline",
        "set_display_mode",
        "answer",
        "clarify",
        "cancelled",
    ]
    message: Line
    channels: Annotated[list[ShortText], Field(max_length=64)]
    primary_channel: str | None
    finding_ids: Annotated[list[ShortText], Field(max_length=8)]
    display_mode: DisplayMode | None
    seek_sample_index: Annotated[int, JsonInteger, Field(ge=0)] | None
    session_generation: Counter
    stream_id: str | None


AssistantDocument = Annotated[AssistantSnapshot | IntentResult, Field(discriminator="type")]
_DOCUMENT = TypeAdapter[AssistantSnapshot | IntentResult](AssistantDocument)


def _describe(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = "/" + "/".join(str(part) for part in error["loc"])
    return f"{location} {error['msg']}"


def semantic_issue(document: AssistantSnapshot | IntentResult) -> str | None:
    if not isinstance(document, AssistantSnapshot):
        return None
    for index, finding in enumerate(document.findings):
        if finding.last_sample_index < finding.first_sample_index:
            return f"/findings/{index}/lastSampleIndex is before firstSampleIndex"
        if finding.last_sample_time_us < finding.first_sample_time_us:
            return f"/findings/{index}/lastSampleTimeUs is before firstSampleTimeUs"
        if not math.isfinite(finding.nominal_sample_rate_hz):
            return f"/findings/{index}/nominalSampleRateHz is not finite"
        labels: set[str] = set()
        for channel_index, channel in enumerate(finding.channels):
            if channel.label in labels:
                return f"/findings/{index}/channels/{channel_index}/label duplicates an earlier channel"
            labels.add(channel.label)
            values = (
                channel.power_uv2,
                channel.baseline_uv2,
                channel.change_db,
                channel.rms_uv,
                channel.accepted_sample_fraction,
            )
            if any(not math.isfinite(value) for value in values):
                return f"/findings/{index}/channels/{channel_index} has a non-finite measurement"
    return None


def _coerce_version(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    version = value.get("schemaVersion")
    if type(version) is float and version.is_integer():
        return {**value, "schemaVersion": int(version)}
    return value


def parse_document(value: Any) -> AssistantSnapshot | IntentResult:
    """Parse a dict or JSON text. Raises ProtocolError."""
    if isinstance(value, (str, bytes)):
        try:
            value = decode_json(value)
        except (ValueError, UnicodeDecodeError):
            raise ProtocolError("json", "document is not valid JSON") from None
    if isinstance(value, dict):
        version = value.get("schemaVersion")
        if type(version) in (int, float) and type(version) is not bool and version != SCHEMA_VERSION:
            raise ProtocolError(
                "unsupported-version",
                f"schemaVersion {version} is not supported (expected {SCHEMA_VERSION})",
            )
    try:
        document = _DOCUMENT.validate_python(_coerce_version(value))
    except ValidationError as exc:
        raise ProtocolError("schema", _describe(exc)) from None
    issue = semantic_issue(document)
    if issue is not None:
        raise ProtocolError("semantic", issue)
    return document


def document_dict(document: AssistantSnapshot | IntentResult) -> dict[str, Any]:
    return document.model_dump(by_alias=True, mode="json")
