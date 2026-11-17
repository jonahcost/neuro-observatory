from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("neuro-engine")
except PackageNotFoundError:
    __version__ = "0.0.0"


def main() -> None:
    from neuro_engine.cli import main as cli_main

    raise SystemExit(cli_main())
