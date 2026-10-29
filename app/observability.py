import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

from app.database import Settings


request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id",
    default=None,
)
STRUCTURED_LOG_FIELDS = (
    "event",
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        contextual_request_id = request_id_context.get()
        if contextual_request_id:
            payload["request_id"] = contextual_request_id
        for field_name in STRUCTURED_LOG_FIELDS:
            value = getattr(record, field_name, None)
            if value is not None:
                payload[field_name] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level)

    # The request middleware emits one consistent access event per request.
    logging.getLogger("uvicorn.access").disabled = settings.log_format == "json"


def set_request_id(request_id: str) -> contextvars.Token[str | None]:
    return request_id_context.set(request_id)


def reset_request_id(token: contextvars.Token[str | None]) -> None:
    request_id_context.reset(token)
