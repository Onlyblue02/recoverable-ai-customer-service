from fastapi.testclient import TestClient

from customer_service.main import create_app
from mock_business.main import create_app as create_mock_app


def test_racs_liveness() -> None:
    response = TestClient(create_app()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mock_business_liveness() -> None:
    response = TestClient(create_mock_app()).get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
