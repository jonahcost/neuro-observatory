from __future__ import annotations

from pathlib import Path

import pytest

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

    import asyncio

    assert asyncio.run(start()) == "not-installed"
    assert runtime.status == "unavailable"
