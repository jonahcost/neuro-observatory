"""Assistant v1 fixtures must classify the same way in Python and TypeScript."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from neuro_engine.protocol.assistant_v1 import document_dict, parse_document
from neuro_engine.protocol.v2 import ProtocolError, decode_json

ROOT = Path(__file__).resolve().parents[3] / "packages" / "protocol"
FIXTURE_ROOT = ROOT / "fixtures" / "assistant-v1"
SCHEMA = json.loads((ROOT / "schemas" / "assistant.v1.schema.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
CASES = MANIFEST["cases"]
VALIDATOR = Draft202012Validator(SCHEMA)


def _text(relative: str) -> str:
    return (FIXTURE_ROOT / relative).read_text(encoding="utf-8")


def test_manifest_covers_every_outcome_and_every_file() -> None:
    assert {case["expect"] for case in CASES} == set(MANIFEST["expectValues"])
    on_disk = {path.relative_to(FIXTURE_ROOT).as_posix() for path in FIXTURE_ROOT.glob("*/*") if path.is_file()}
    assert on_disk == {case["file"] for case in CASES}


@pytest.mark.parametrize("case", CASES, ids=[case["file"] for case in CASES])
def test_schema_and_python_agree(case: dict) -> None:
    text = _text(case["file"])
    if case["expect"] == "json":
        with pytest.raises(ValueError):
            decode_json(text)
        return
    decoded = decode_json(text)
    schema_valid = VALIDATOR.is_valid(decoded)
    assert schema_valid is (case["expect"] in {"valid", "semantic"})
    if case["expect"] == "valid":
        parsed = parse_document(text)
        assert json.loads(json.dumps(document_dict(parsed))) == decoded
        assert "samples" not in json.dumps(document_dict(parsed))
        return
    with pytest.raises(ProtocolError) as excinfo:
        parse_document(text)
    assert excinfo.value.kind == case["expect"]
    assert excinfo.value.detail
