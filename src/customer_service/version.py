"""Project version sourced from the repository's release manifest."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PACKAGE_NAME = "recoverable-ai-customer-service"


def project_version() -> str:
    """Return the sole project version declared in ``pyproject.toml``."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return str(document["project"]["version"])

    try:
        return version(PACKAGE_NAME)
    except PackageNotFoundError as error:
        message = "Project version metadata is unavailable."
        raise RuntimeError(message) from error


PROJECT_VERSION = project_version()
