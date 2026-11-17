"""Optional llama.cpp child. The browser never talks to it.

Weights are not downloaded. `NEURO_ENGINE_ASSISTANT=1` is required before a
checksum-verified manifest is started. Acquisition does not wait on it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import URLError

from neuro_engine.recordings.v1 import RecordingError

MODEL_DIR = "models"
MANIFEST_NAME = "assistant.json"
INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent"],
    "properties": {
        "intent": {
            "enum": [
                "emphasize_channels",
                "seek_to_finding",
                "add_marker",
                "lock_baseline",
                "set_display_mode",
                "answer",
                "clarify",
            ]
        },
        "channels": {"type": "array", "maxItems": 16, "items": {"type": "string"}},
        "findingId": {"type": "string"},
        "findingIds": {"type": "array", "maxItems": 8, "items": {"type": "string"}},
        "displayMode": {"enum": ["pial", "white", "inflated", "holographic", "grid"]},
        "markerLabel": {"type": "string"},
        "answer": {"type": "string"},
        "clarification": {"type": "string"},
    },
}


class ModelUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class LlamaRuntime:
    def __init__(self, data_dir: Path | None, *, port: int = 8010, enabled: bool = False) -> None:
        self.data_dir = data_dir
        self.port = port
        self.enabled = enabled
        self.status = "unavailable"
        self.reason = "not-installed"
        self._process: asyncio.subprocess.Process | None = None
        self._inflight: asyncio.Task[Any] | None = None
        self._transport = None
        self._manifest: dict[str, Any] | None = None

    def cancel(self) -> None:
        task = self._inflight
        if task is not None and not task.done():
            task.cancel()

    def manifest_path(self) -> Path | None:
        if self.data_dir is None:
            return None
        return self.data_dir / MODEL_DIR / MANIFEST_NAME

    def install(self, gguf: Path, sha256: str, llama_server: str, *, quantization: str, context: int) -> Path:
        if self.data_dir is None:
            raise RecordingError("no-data-dir", "a data directory is required to install model weights")
        digest = hashlib.sha256(gguf.read_bytes()).hexdigest()
        if digest != sha256.lower():
            raise RecordingError("checksum-mismatch", "model file checksum does not match")
        destination_dir = self.data_dir / MODEL_DIR
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / gguf.name
        if destination.resolve() != gguf.resolve():
            destination.write_bytes(gguf.read_bytes())
        manifest = {
            "schemaVersion": 1,
            "modelFile": destination.name,
            "sha256": digest,
            "llamaServer": llama_server,
            "port": self.port,
            "context": context,
            "quantization": quantization,
            "gpuLayers": 0,
        }
        path = destination_dir / MANIFEST_NAME
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    async def startup(self) -> None:
        if not self.enabled:
            self.status = "unavailable"
            self.reason = "disabled"
            return
        path = self.manifest_path()
        if path is None or not path.is_file():
            self.status = "unavailable"
            self.reason = "not-installed"
            return
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.status = "unavailable"
            self.reason = "checksum"
            return
        model_path = path.parent / str(manifest.get("modelFile", ""))
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest() if model_path.is_file() else ""
        if digest != str(manifest.get("sha256", "")):
            self.status = "unavailable"
            self.reason = "checksum"
            return
        binary = str(manifest.get("llamaServer", ""))
        resolved = binary if Path(binary).is_file() else shutil.which(binary)
        if resolved is None:
            self.status = "unavailable"
            self.reason = "runtime-missing"
            return
        self._manifest = manifest
        self.port = int(manifest.get("port", self.port))
        self.status = "starting"
        self._process = await asyncio.create_subprocess_exec(
            resolved,
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "-m",
            str(model_path),
            "-c",
            str(int(manifest.get("context", 2048))),
            "--n-gpu-layers",
            str(int(manifest.get("gpuLayers", 0))),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        asyncio.create_task(self._await_ready())

    async def _await_ready(self) -> None:
        for _ in range(20):
            if self._process is None or self._process.returncode is not None:
                self.status = "unavailable"
                self.reason = "runtime-missing"
                return
            try:
                await asyncio.to_thread(self._ping)
            except (URLError, TimeoutError, OSError):
                await asyncio.sleep(0.25)
                continue
            self.status = "ready"
            self.reason = ""
            return
        self.status = "unavailable"
        self.reason = "runtime-missing"

    def _ping(self) -> None:
        with request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=0.5) as response:
            response.read()

    async def shutdown(self) -> None:
        self.cancel()
        process = self._process
        self._process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()

    def use_transport(self, transport) -> None:
        """Test hook. Does not spawn a process."""
        self._transport = transport
        self.status = "ready"
        self.reason = ""

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        if self.status != "ready" and self._transport is None:
            raise ModelUnavailable(self.reason or "not-installed")

        async def run() -> dict[str, Any]:
            if self._transport is not None:
                return await self._transport(messages, INTENT_SCHEMA)
            return await asyncio.to_thread(self._post, messages)

        task = asyncio.create_task(run())
        self._inflight = task
        try:
            return await asyncio.wait_for(task, timeout=30)
        finally:
            if self._inflight is task:
                self._inflight = None

    def _post(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload = {
            "model": "local",
            "temperature": 0.1,
            "max_tokens": 400,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "assistant_intent", "strict": True, "schema": INTENT_SCHEMA},
            },
        }
        body = json.dumps(payload).encode()
        req = request.Request(
            f"http://127.0.0.1:{self.port}/v1/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
