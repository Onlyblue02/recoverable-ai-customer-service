from urllib.parse import quote

import httpx
from pydantic import ValidationError

from customer_service.tools.order_tool import OrderGatewayOutcome, OrderGatewayStatus
from customer_service.tools.schemas import AuthorizedOrderFacts, OrderErrorCode


class OrderGatewayError(RuntimeError):
    """Raised when the Mock Business API violates the order boundary contract."""


class HttpOrderGateway:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def lookup(self, *, current_user_id: str, order_id: str) -> OrderGatewayOutcome:
        encoded_order_id = quote(order_id, safe="")
        try:
            response = self._client.get(
                f"/orders/{encoded_order_id}",
                params={"current_user_id": current_user_id},
            )
        except httpx.HTTPError as error:
            raise OrderGatewayError("Mock Business order request failed") from error
        if response.status_code == 200:
            try:
                order = AuthorizedOrderFacts.model_validate(response.json())
            except (ValueError, ValidationError) as error:
                raise OrderGatewayError("Mock Business order response violates contract") from error
            if order.order_id != order_id:
                raise OrderGatewayError("Mock Business order response does not match the request")
            return OrderGatewayOutcome(status=OrderGatewayStatus.FOUND, order=order)

        expected_errors = {
            404: (OrderErrorCode.ORDER_UNAVAILABLE, OrderGatewayStatus.NOT_FOUND),
        }
        expected = expected_errors.get(response.status_code)
        if expected is None:
            raise OrderGatewayError(
                f"unexpected Mock Business order response status: {response.status_code}"
            )

        expected_code, gateway_status = expected
        try:
            payload = response.json()
        except ValueError as error:
            raise OrderGatewayError(
                "Mock Business order error response violates contract"
            ) from error
        if not isinstance(payload, dict) or payload.get("error_code") != expected_code.value:
            raise OrderGatewayError("Mock Business order error response violates contract")
        return OrderGatewayOutcome(status=gateway_status)
