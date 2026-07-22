from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from mock_business.repository import OrderRepository, OrderSourceStatus
from mock_business.schemas import (
    OrderBoundaryErrorCode,
    OrderErrorResponse,
    OrderResponse,
)


def create_order_router(repository: OrderRepository) -> APIRouter:
    router = APIRouter()

    @router.get("/orders/{order_id}", response_model=OrderResponse)
    def get_order(
        order_id: Annotated[str, Path(min_length=1)],
        current_user_id: Annotated[str, Query(min_length=1)],
    ) -> OrderResponse | JSONResponse:
        result = repository.lookup(
            current_user_id=current_user_id,
            order_id=order_id,
        )
        if result.status in {
            OrderSourceStatus.NOT_FOUND,
            OrderSourceStatus.UNAUTHORIZED,
        }:
            error = OrderErrorResponse(
                error_code=OrderBoundaryErrorCode.ORDER_UNAVAILABLE,
                message="无法访问该订单。",
            )
            return JSONResponse(status_code=404, content=error.model_dump(mode="json"))

        assert result.order is not None
        return OrderResponse.from_stored(result.order)

    return router
