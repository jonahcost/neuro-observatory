"""ASGI entry point: `uvicorn neuro_engine.main:app --host 127.0.0.1`."""

from neuro_engine.app import create_app

app = create_app()
