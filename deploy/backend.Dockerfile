# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.11.23 AS uv
FROM python:3.12.13-slim-bookworm

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "customer_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
