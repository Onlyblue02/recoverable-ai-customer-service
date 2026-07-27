"""T-204's constrained model-provider boundary."""

from customer_service.model_gateway.deepseek import DeepSeekModelGateway
from customer_service.model_gateway.fake import FakeModelGateway
from customer_service.model_gateway.gateway import ModelGateway

__all__ = ["DeepSeekModelGateway", "FakeModelGateway", "ModelGateway"]
