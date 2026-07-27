from typing import Protocol

from customer_service.model_gateway.schemas import ModelRequest, ModelResponse


class ModelGateway(Protocol):
    """Port for language suggestions; deterministic services retain final authority."""

    def generate(self, request: ModelRequest) -> ModelResponse: ...
