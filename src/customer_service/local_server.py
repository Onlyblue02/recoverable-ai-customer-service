"""Local demonstration server entry point with an environment-configurable port."""

import os
from argparse import ArgumentParser
from collections.abc import Mapping, Sequence

import uvicorn

DEFAULT_BACKEND_PORT = 8000
PORT_ENVIRONMENT_VARIABLE = "RACS_BACKEND_PORT"


def backend_port(environment: Mapping[str, str] | None = None) -> int:
    """Read and validate the local API port without changing the default."""
    values = environment if environment is not None else os.environ
    raw_port = values.get(PORT_ENVIRONMENT_VARIABLE, str(DEFAULT_BACKEND_PORT))

    try:
        port = int(raw_port)
    except ValueError as error:
        message = f"{PORT_ENVIRONMENT_VARIABLE} must be an integer port."
        raise ValueError(message) from error

    if not 1 <= port <= 65535:
        message = f"{PORT_ENVIRONMENT_VARIABLE} must be between 1 and 65535."
        raise ValueError(message)
    return port


def run(arguments: Sequence[str] | None = None) -> None:
    """Start the local FastAPI server using the configured loopback port."""
    parser = ArgumentParser(add_help=False)
    parser.add_argument("--demo-token")
    parser.add_argument("--demo-repository")
    parser.parse_args(arguments)
    uvicorn.run("customer_service.main:app", host="127.0.0.1", port=backend_port(), reload=False)


if __name__ == "__main__":
    run()
