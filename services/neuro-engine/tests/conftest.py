from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

PROTOCOL_ROOT = Path(__file__).resolve().parents[3] / "packages" / "protocol"
SCHEMA_PATH = PROTOCOL_ROOT / "schemas" / "eeg-stream.v2.schema.json"
FIXTURE_ROOT = PROTOCOL_ROOT / "fixtures" / "v2"
ANATOMY_SCHEMA_PATH = PROTOCOL_ROOT / "schemas" / "anatomy-asset.v1.schema.json"
ANATOMY_FIXTURE_ROOT = PROTOCOL_ROOT / "fixtures" / "anatomy-v1"


def load_fixture_text(relative: str) -> str:
    return (FIXTURE_ROOT / relative).read_text(encoding="utf-8")


def load_fixture_json(relative: str) -> Any:
    return json.loads(load_fixture_text(relative))


def _validator(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="session")
def schema_validator() -> Draft202012Validator:
    return _validator(SCHEMA_PATH)


@pytest.fixture(scope="session")
def anatomy_schema_validator() -> Draft202012Validator:
    return _validator(ANATOMY_SCHEMA_PATH)
