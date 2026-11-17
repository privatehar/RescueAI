"""RescueAI: AI-powered job failure detection, diagnosis and recovery."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rescueai")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"
