from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="RACS Mock Business API", version="0.1.0")

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
