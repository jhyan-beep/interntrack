import json
import logging

import pytest
from httpx import AsyncClient

from app.observability import JsonLogFormatter, reset_request_id, set_request_id


def test_json_formatter_emits_structured_request_context() -> None:
    record = logging.LogRecord(
        name="interntrack.requests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Request completed",
        args=(),
        exc_info=None,
    )
    record.event = "http_request"
    record.method = "GET"
    record.path = "/health/ready"
    record.status_code = 200
    record.duration_ms = 12.3
    token = set_request_id("request-123")
    try:
        payload = json.loads(JsonLogFormatter().format(record))
    finally:
        reset_request_id(token)

    assert payload["level"] == "INFO"
    assert payload["logger"] == "interntrack.requests"
    assert payload["event"] == "http_request"
    assert payload["request_id"] == "request-123"
    assert payload["path"] == "/health/ready"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 12.3
    assert payload["timestamp"].endswith("+00:00")


@pytest.mark.anyio
async def test_invalid_request_id_is_replaced(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.get(
        "/health/live",
        headers={"X-Request-ID": "invalid request id with spaces"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "invalid request id with spaces"
    assert response.headers["x-request-id"]
