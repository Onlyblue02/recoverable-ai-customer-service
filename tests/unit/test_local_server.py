import pytest

from customer_service.local_server import DEFAULT_BACKEND_PORT, backend_port


def test_backend_port_defaults_to_8000() -> None:
    assert backend_port({}) == DEFAULT_BACKEND_PORT


def test_backend_port_reads_the_local_environment_variable() -> None:
    assert backend_port({"RACS_BACKEND_PORT": "8010"}) == 8010


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_backend_port_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        backend_port({"RACS_BACKEND_PORT": value})
