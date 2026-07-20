from fastapi import FastAPI

from customer_service.interfaces.api.routes.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="RACS API", version="0.2.0")
    app.include_router(health_router)
    return app


app = create_app()
