from fastapi import FastAPI

from customer_service.interfaces.api.routes.approvals import router as approval_router
from customer_service.interfaces.api.routes.conversations import router as conversation_router
from customer_service.interfaces.api.routes.health import router as health_router
from customer_service.version import PROJECT_VERSION


def create_app() -> FastAPI:
    app = FastAPI(title="RACS API", version=PROJECT_VERSION)
    app.include_router(health_router)
    app.include_router(conversation_router)
    app.include_router(approval_router)
    return app


app = create_app()
