"""Engine settings from environment variables. Invalid settings fail at startup."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from neuro_engine.acquisition.base import DeviceConfigError
from neuro_engine.acquisition.service import ReconnectPolicy
from neuro_engine.acquisition.synthetic import SyntheticConfig

DEFAULT_ALLOWED_ORIGINS = frozenset(
    {
        "http://localhost:4200",
        "http://127.0.0.1:4200",
        "http://localhost:4300",
        "http://127.0.0.1:4300",
    }
)
ENV_PREFIX = "NEURO_ENGINE_"


class SettingsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EngineSettings:
    device: Literal["synthetic"] = "synthetic"
    synthetic: SyntheticConfig = field(default_factory=SyntheticConfig)
    live_view_queue_blocks: int = 25
    status_interval_s: float = 1.0
    allowed_origins: frozenset[str] = DEFAULT_ALLOWED_ORIGINS
    reconnect: ReconnectPolicy = field(default_factory=ReconnectPolicy)
    # None selects NEURO_ENGINE_DATA_DIR or the per-user default (see neuro_engine.datasets.storage).
    data_dir: Path | None = None

    def __post_init__(self) -> None:
        if self.device != "synthetic":
            raise SettingsError(f"unsupported device {self.device!r}; available: synthetic")
        if not 1 <= self.live_view_queue_blocks <= 10_000:
            raise SettingsError("live_view_queue_blocks must be in [1, 10000]")
        if not 0 < self.status_interval_s <= 60:
            raise SettingsError("status_interval_s must be in (0, 60]")
        for origin in self.allowed_origins:
            parsed = urlsplit(origin)
            if (
                origin == "*"
                or parsed.scheme not in ("http", "https")
                or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                raise SettingsError("allowed_origins must contain explicit loopback HTTP(S) origins; wildcard CORS is forbidden")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> EngineSettings:
        env = os.environ if env is None else env

        def get(name: str) -> str | None:
            value = env.get(ENV_PREFIX + name)
            return value.strip() if value is not None and value.strip() else None

        def get_int(name: str, default: int) -> int:
            raw = get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                raise SettingsError(f"{ENV_PREFIX}{name} must be an integer") from None

        defaults = SyntheticConfig()
        try:
            synthetic = SyntheticConfig(
                seed=get_int("SYNTHETIC_SEED", defaults.seed),
                block_size=get_int("SYNTHETIC_BLOCK_SIZE", defaults.block_size),
            )
        except DeviceConfigError as exc:
            raise SettingsError(str(exc)) from None
        origins = get("ALLOWED_ORIGINS")
        data_dir = get("DATA_DIR")
        return cls(
            data_dir=Path(data_dir).expanduser() if data_dir else None,
            device=get("DEVICE") or "synthetic",
            synthetic=synthetic,
            live_view_queue_blocks=get_int("LIVE_VIEW_QUEUE_BLOCKS", 25),
            allowed_origins=(
                frozenset(o.strip() for o in origins.split(",") if o.strip()) if origins else DEFAULT_ALLOWED_ORIGINS
            ),
        )
