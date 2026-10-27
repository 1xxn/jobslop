"""jobslop – ein lokaler, KI-gesteuerter Bewerbungs-Autopilot."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("jobslop")  # einzige Quelle: pyproject.toml
except PackageNotFoundError:  # pragma: no cover - nur ohne Installation (z. B. Quellordner im PYTHONPATH)
    __version__ = "0.0.0"
