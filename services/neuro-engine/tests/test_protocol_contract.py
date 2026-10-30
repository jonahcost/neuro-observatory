"""Cross-language contract: the canonical JSON Schema, the Pydantic mirror and the
TypeScript validator must classify every shared fixture identically."""

from __future__ import annotations

import json
import math

import pytest
from conftest import FIXTURE_ROOT, load_fixture_json, load_fixture_text
from jsonschema import Draft202012Validator

from neuro_engine.protocol import v2

MANIFEST = load_fixture_json("manifest.json")
CASES = MANIFEST["cases"]


def _context(case: dict) -> v2.StreamMetadata | None:
    if "context" not in case:
        return None
    message = v2.parse_server_message(load_fixture_text(case["context"]))
    assert isinstance(message, v2.StreamMetadata)
    return message


def test_manifest_covers_every_outcome_and_every_file() -> None:
    assert {c["expect"] for c in CASES} == set(MANIFEST["expectValues"])
    on_disk = {p.relative_to(FIXTURE_ROOT).as_posix() for p in FIXTURE_ROOT.glob("*/*") if p.parent.name != "integrity"}
    assert on_disk == {c["file"] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_canonical_schema_agrees_with_expectation(case: dict, schema_validator: Draft202012Validator) -> None:
    text = load_fixture_text(case["file"])
    if case["expect"] == "json":
        with pytest.raises(ValueError):
            json.loads(text)
        return
    schema_valid = schema_validator.is_valid(json.loads(text))
    # Semantic rules are, by definition, outside what the schema can express.
    assert schema_valid is (case["expect"] in ("valid", "semantic"))


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_python_validator_classifies_like_typescript(case: dict) -> None:
    text = load_fixture_text(case["file"])
    if case["expect"] == "valid":
        v2.parse_server_message(text, _context(case))
        return
    with pytest.raises(v2.ProtocolError) as excinfo:
        v2.parse_server_message(text, _context(case))
    assert excinfo.value.kind == case["expect"]
    assert excinfo.value.detail


@pytest.mark.parametrize("case", [c for c in CASES if c["expect"] == "valid"], ids=lambda c: c["file"])
def test_valid_fixtures_round_trip_byte_for_value(case: dict) -> None:
    message = v2.parse_server_message(load_fixture_text(case["file"]), _context(case))
    assert json.loads(v2.encode(message)) == load_fixture_json(case["file"])


def test_error_details_never_echo_sample_values() -> None:
    block = load_fixture_json("valid/block-16ch.json")
    block["samples"][0] = [123456.789, "x"]
    with pytest.raises(v2.ProtocolError) as excinfo:
        v2.validate_server_message(block)
    assert "123456.789" not in excinfo.value.detail


def test_encode_rejects_non_finite_values() -> None:
    message = v2.parse_server_message(load_fixture_text("valid/block-16ch.json"))
    assert isinstance(message, v2.EegBlock)
    bad = message.model_copy(update={"samples": [[math.nan] * message.sample_count] * len(message.samples)})
    with pytest.raises(v2.ProtocolError) as excinfo:
        v2.encode(bad)
    assert excinfo.value.kind == "semantic"


def test_float64_values_round_trip_exactly() -> None:
    values = [0.1 + 0.2, -1e-12, 123.456789012345, 5e-324, 2.0**52 + 0.5]
    block = load_fixture_json("valid/block-16ch.json")
    block["samples"] = [values for _ in block["samples"]]
    block["sampleCount"] = len(values)
    message = v2.validate_server_message(block)
    decoded = json.loads(v2.encode(message))
    assert decoded["samples"][0] == values


def test_snake_case_keys_are_rejected_on_the_wire() -> None:
    block = load_fixture_json("valid/block-16ch.json")
    block["stream_id"] = block.pop("streamId")
    with pytest.raises(v2.ProtocolError) as excinfo:
        v2.validate_server_message(block)
    assert excinfo.value.kind == "schema"


def test_booleans_are_not_integers() -> None:
    block = load_fixture_json("valid/block-16ch.json")
    block["blockSequence"] = True
    with pytest.raises(v2.ProtocolError):
        v2.validate_server_message(block)
