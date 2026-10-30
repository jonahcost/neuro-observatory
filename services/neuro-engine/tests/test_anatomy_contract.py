"""Cross-language anatomy contract: the canonical JSON Schema, the Pydantic mirror
and the TypeScript validator must classify every shared fixture identically."""

from __future__ import annotations

import json

import pytest
from conftest import ANATOMY_FIXTURE_ROOT
from jsonschema import Draft202012Validator

from neuro_engine.protocol import anatomy_v1
from neuro_engine.protocol.v2 import ProtocolError

MANIFEST = json.loads((ANATOMY_FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["cases"]


def _text(case: dict) -> str:
    return (ANATOMY_FIXTURE_ROOT / case["file"]).read_text(encoding="utf-8")


def test_manifest_covers_every_outcome_and_every_file() -> None:
    assert {c["expect"] for c in CASES} == set(MANIFEST["expectValues"])
    on_disk = {p.relative_to(ANATOMY_FIXTURE_ROOT).as_posix() for p in ANATOMY_FIXTURE_ROOT.glob("*/*")}
    assert on_disk == {c["file"] for c in CASES}


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_canonical_schema_agrees_with_expectation(case: dict, anatomy_schema_validator: Draft202012Validator) -> None:
    text = _text(case)
    if case["expect"] == "json":
        with pytest.raises(ValueError):
            json.loads(text)
        return
    schema_valid = anatomy_schema_validator.is_valid(json.loads(text))
    assert schema_valid is (case["expect"] in ("valid", "semantic"))


@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_python_validator_classifies_like_typescript(case: dict) -> None:
    if case["expect"] == "valid":
        anatomy_v1.parse_document(_text(case))
        return
    with pytest.raises(ProtocolError) as excinfo:
        anatomy_v1.parse_document(_text(case))
    assert excinfo.value.kind == case["expect"]
    assert excinfo.value.detail


@pytest.mark.parametrize("case", [c for c in CASES if c["expect"] == "valid"], ids=lambda c: c["file"])
def test_valid_fixtures_round_trip(case: dict) -> None:
    document = anatomy_v1.parse_document(_text(case))
    assert anatomy_v1.to_wire_dict(document) == json.loads(_text(case))


def test_wire_serialization_revalidates_mutated_nested_models() -> None:
    text = (ANATOMY_FIXTURE_ROOT / "valid/asset-tetrahedra.json").read_text()
    document = anatomy_v1.parse_document(text)
    assert isinstance(document, anatomy_v1.AnatomyAsset)
    object.__setattr__(document.provenance.sources[0], "path", "../escaped")
    with pytest.raises(ProtocolError):
        anatomy_v1.to_wire_dict(document)
