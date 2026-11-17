from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.error import URLError

import pytest

from neuro_engine.assistant import runtime as runtime_module
from neuro_engine.assistant.runtime import LlamaRuntime
from neuro_engine.recordings.v1 import RecordingError


def test_install_rejects_a_bad_checksum_and_accepts_a_good_one(tmp_path: Path) -> None:
    gguf = tmp_path / "tiny.gguf"
    gguf.write_bytes(b"not-a-real-model")
    runtime = LlamaRuntime(tmp_path / "data", enabled=False)
    with pytest.raises(RecordingError) as exc:
        runtime.install(gguf, "0" * 64, "llama-server", quantization="Q4_K_M", context=512)
    assert exc.value.code == "checksum-mismatch"
    import hashlib

    digest = hashlib.sha256(gguf.read_bytes()).hexdigest()
    path = runtime.install(gguf, digest, "llama-server", quantization="Q4_K_M", context=512)
    assert path.is_file()
    assert (tmp_path / "data" / "models" / "tiny.gguf").is_file()


def test_startup_without_a_manifest_stays_unavailable(tmp_path: Path) -> None:
    runtime = LlamaRuntime(tmp_path, enabled=True)

    async def start() -> str:

        await runtime.startup()
        return runtime.reason

    assert asyncio.run(start()) == "not-installed"
    assert runtime.status == "unavailable"


def test_cancel_closes_the_inflight_connection(tmp_path: Path) -> None:
    runtime = LlamaRuntime(tmp_path, enabled=False)
    closed = {"value": False}

    class _Connection:
        def close(self) -> None:
            closed["value"] = True

    runtime._connection = _Connection()  # type: ignore[assignment]
    runtime.cancel()
    assert closed["value"] is True
    assert runtime._connection is None


class _Alive:
    returncode = None


def test_ready_wait_accepts_health_after_the_old_five_second_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LlamaRuntime(tmp_path, enabled=True)
    runtime.status = "starting"
    runtime._process = _Alive()  # type: ignore[assignment]
    calls = {"n": 0}

    def late() -> None:
        calls["n"] += 1
        if calls["n"] < 30:
            raise URLError("still-loading")

    monkeypatch.setattr(runtime, "_ping", late)
    monkeypatch.setattr(runtime_module, "READY_POLL_S", 0.0)
    asyncio.run(runtime._await_ready())
    assert calls["n"] == 30
    assert runtime.status == "ready"
    assert runtime.reason == ""


def test_ready_wait_gives_up_when_health_never_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = LlamaRuntime(tmp_path, enabled=True)
    runtime.status = "starting"
    runtime._process = _Alive()  # type: ignore[assignment]
    def down() -> None:
        raise URLError("down")

    monkeypatch.setattr(runtime_module, "READY_TIMEOUT_S", 0.0)
    monkeypatch.setattr(runtime, "_ping", down)
    asyncio.run(runtime._await_ready())
    assert runtime.status == "unavailable"
    assert runtime.reason == "runtime-missing"
