"""Protocol v2 models mirroring packages/protocol/schemas/eeg-stream.v2.schema.json.

The JSON Schema is canonical. These models are kept in parity by the shared
fixture tests (tests/test_protocol_contract.py). Structural rules live in the
models; rules JSON Schema cannot express live in `semantic_issue`, exactly as
in the TypeScript validator.
"""

from __future__ import annotations

import json
import math
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_serializer,
)
from pydantic.alias_generators import to_camel

SCHEMA_VERSION: Literal[2] = 2
MAX_SAFE_INTEGER = 2**53 - 1

ParseErrorKind = Literal["json", "schema", "unsupported-version", "semantic"]

Counter = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
StreamId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,128}$")]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]


class _Message(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        # Non-finite values are rejected by `semantic_issue` (parity with TypeScript).
        allow_inf_nan=True,
    )


class DeviceInfo(_Message):
    kind: Slug
    model: ShortText
    device_id: ShortText
    adapter_version: ShortText
    firmware_version: ShortText | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_firmware(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if self.firmware_version is None:
            data.pop("firmwareVersion", None)
            data.pop("firmware_version", None)
        return data


class SyntheticProvenance(_Message):
    kind: Literal["synthetic"]
    generator: ShortText
    generator_version: ShortText
    seed: Counter
    config_hash: Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class DeviceProvenance(_Message):
    kind: Literal["device"]


class ChannelSpec(_Message):
    index: Counter
    label: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    type: Literal["EEG", "EOG", "EMG", "ECG", "MISC"]
    unit: Literal["uV"]
    reference: ShortText


class ClockAnchor(_Message):
    monotonic_us: Counter
    unix_time_us: Counter


class Timebase(_Message):
    clock: Literal["engine-monotonic"]
    unit: Literal["us"]
    timestamp_source: Literal["synthetic-nominal", "host-receipt-fitted", "device-clock"]
    anchor: ClockAnchor


class StreamMetadata(_Message):
    type: Literal["stream.metadata"]
    schema_version: Literal[2]
    stream_id: StreamId
    device: DeviceInfo
    provenance: Annotated[SyntheticProvenance | DeviceProvenance, Field(discriminator="kind")]
    nominal_sample_rate_hz: Annotated[float, Field(gt=0, le=100_000)]
    layout: Literal["channel-major"]
    channels: Annotated[list[ChannelSpec], Field(min_length=1, max_length=1024)]
    timebase: Timebase


class EegBlock(_Message):
    type: Literal["eeg.block"]
    schema_version: Literal[2]
    stream_id: StreamId
    block_sequence: Counter
    first_sample_index: Counter
    sample_count: Annotated[int, Field(ge=1, le=10_000)]
    first_sample_time_us: Counter
    dropped_samples_before: Counter
    samples: Annotated[
        list[Annotated[list[float], Field(min_length=1, max_length=10_000)]],
        Field(min_length=1, max_length=1024),
    ]


class StreamCounters(_Message):
    samples_acquired: Counter
    acquisition_gap_samples: Counter
    rejected_blocks: Counter
    blocks_dropped_for_client: Counter
    effective_sample_rate_hz: Annotated[float, Field(ge=0)] | None


class StreamError(_Message):
    code: Slug
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]


class StreamStatus(_Message):
    type: Literal["stream.status"]
    schema_version: Literal[2]
    stream_id: StreamId | None
    state: Literal["idle", "connecting", "streaming", "reconnecting", "stopped", "failed"]
    at_us: Counter
    counters: StreamCounters
    error: StreamError | None


ServerMessage = Annotated[StreamMetadata | EegBlock | StreamStatus, Field(discriminator="type")]
_SERVER_MESSAGE = TypeAdapter[StreamMetadata | EegBlock | StreamStatus](ServerMessage)


class ProtocolError(ValueError):
    def __init__(self, kind: ParseErrorKind, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def _metadata_issue(metadata: StreamMetadata) -> str | None:
    labels: set[str] = set()
    for position, channel in enumerate(metadata.channels):
        if channel.index != position:
            return f"/channels/{position}/index must equal its position {position}"
        if channel.label in labels:
            return f"/channels/{position}/label duplicates an earlier channel label"
        labels.add(channel.label)
    return None


def _block_issue(block: EegBlock, metadata: StreamMetadata | None) -> str | None:
    for channel, row in enumerate(block.samples):
        if len(row) != block.sample_count:
            return f"/samples/{channel} has {len(row)} samples but sampleCount is {block.sample_count}"
        for sample, value in enumerate(row):
            if not math.isfinite(value):
                return f"/samples/{channel}/{sample} is not a finite number"
    if metadata is not None:
        if block.stream_id != metadata.stream_id:
            return f"block belongs to stream {block.stream_id}, active stream is {metadata.stream_id}"
        if len(block.samples) != len(metadata.channels):
            return f"/samples has {len(block.samples)} channels but metadata declares {len(metadata.channels)}"
    return None


def semantic_issue(
    message: StreamMetadata | EegBlock | StreamStatus, metadata: StreamMetadata | None = None
) -> str | None:
    if isinstance(message, StreamMetadata):
        return _metadata_issue(message)
    if isinstance(message, EegBlock):
        return _block_issue(message, metadata)
    return None


def _describe(error: ValidationError) -> str:
    first = error.errors(include_input=False, include_url=False)[0]
    location = "/".join(str(part) for part in first["loc"])
    # Location and rule only; sample values are never echoed.
    return f"/{location} {first['msg']}"


def validate_server_message(
    value: Any, metadata: StreamMetadata | None = None
) -> StreamMetadata | EegBlock | StreamStatus:
    """Validate a decoded JSON value. Raises ProtocolError."""
    if isinstance(value, dict):
        version = value.get("schemaVersion")
        if type(version) in (int, float) and version != SCHEMA_VERSION:
            raise ProtocolError(
                "unsupported-version", f"schemaVersion {version} is not supported (expected {SCHEMA_VERSION})"
            )
    try:
        message = _SERVER_MESSAGE.validate_python(value, by_alias=True, by_name=False)
    except ValidationError as exc:
        raise ProtocolError("schema", _describe(exc)) from None
    issue = semantic_issue(message, metadata)
    if issue is not None:
        raise ProtocolError("semantic", issue)
    return message


def parse_server_message(
    raw: str | bytes, metadata: StreamMetadata | None = None
) -> StreamMetadata | EegBlock | StreamStatus:
    """Parse and validate raw message text. Raises ProtocolError."""
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ProtocolError("json", "message is not valid JSON") from None
    return validate_server_message(value, metadata)


def encode(message: StreamMetadata | EegBlock | StreamStatus, metadata: StreamMetadata | None = None) -> str:
    """Serialize an outgoing message after semantic validation. Raises ProtocolError."""
    issue = semantic_issue(message, metadata)
    if issue is not None:
        raise ProtocolError("semantic", issue)
    return message.model_dump_json()


def to_wire_dict(message: StreamMetadata | EegBlock | StreamStatus) -> dict[str, Any]:
    issue = semantic_issue(message)
    if issue is not None:
        raise ProtocolError("semantic", issue)
    return message.model_dump(mode="json")
