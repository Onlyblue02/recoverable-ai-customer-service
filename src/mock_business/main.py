from pathlib import Path

from fastapi import FastAPI

from customer_service.version import PROJECT_VERSION
from mock_business.repository import OrderRepository
from mock_business.routes.orders import create_order_router

DEFAULT_DATA_MANIFEST = Path(__file__).parents[2] / "data" / "manifest.json"


def create_app(
    *,
    manifest_path: Path = DEFAULT_DATA_MANIFEST,
    order_repository: OrderRepository | None = None,
) -> FastAPI:
    app = FastAPI(title="RACS Mock Business API", version=PROJECT_VERSION)
    repository = order_repository or OrderRepository.from_manifest(manifest_path)
    app.include_router(create_order_router(repository))

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
