from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

PROTOCOL_ROOT = Path(__file__).resolve().parents[3] / "packages" / "protocol"
SCHEMA_PATH = PROTOCOL_ROOT / "schemas" / "eeg-stream.v2.schema.json"
FIXTURE_ROOT = PROTOCOL_ROOT / "fixtures" / "v2"


def load_fixture_text(relative: str) -> str:
    return (FIXTURE_ROOT / relative).read_text(encoding="utf-8")


def load_fixture_json(relative: str) -> Any:
    return json.loads(load_fixture_text(relative))


@pytest.fixture(scope="session")
def schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)
