from __future__ import annotations

import pytest

from neuro_engine.app import create_app
from neuro_engine.config import DEFAULT_ALLOWED_ORIGINS, EngineSettings, SettingsError


def test_defaults_without_environment() -> None:
    settings = EngineSettings.from_env({})
    assert settings.device == "synthetic"
    assert settings.synthetic.seed == 0
    assert settings.synthetic.block_size == 25
    assert settings.allowed_origins == DEFAULT_ALLOWED_ORIGINS


def test_environment_overrides() -> None:
    settings = EngineSettings.from_env(
        {
            "NEURO_ENGINE_SYNTHETIC_SEED": "42",
            "NEURO_ENGINE_SYNTHETIC_BLOCK_SIZE": "5",
            "NEURO_ENGINE_LIVE_VIEW_QUEUE_BLOCKS": "10",
            "NEURO_ENGINE_ALLOWED_ORIGINS": "http://localhost:1420, tauri://localhost",
        }
    )
    assert settings.synthetic.seed == 42
    assert settings.synthetic.block_size == 5
    assert settings.live_view_queue_blocks == 10
    assert settings.allowed_origins == {"http://localhost:1420", "tauri://localhost"}


@pytest.mark.parametrize(
    "env",
    [
        {"NEURO_ENGINE_DEVICE": "openbci"},
        {"NEURO_ENGINE_SYNTHETIC_SEED": "abc"},
        {"NEURO_ENGINE_SYNTHETIC_SEED": "-3"},
        {"NEURO_ENGINE_SYNTHETIC_BLOCK_SIZE": "0"},
        {"NEURO_ENGINE_LIVE_VIEW_QUEUE_BLOCKS": "0"},
    ],
)
def test_invalid_environment_fails_fast(env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SettingsError):
        EngineSettings.from_env(env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SettingsError):
        create_app()
