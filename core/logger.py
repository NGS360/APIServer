"""
Configure the logger.

Deployed environments emit one JSON object per line so that logs are queryable
in CloudWatch Logs Insights -- the traffic inventory described in docs/RBAC.md
depends on aggregating by route, principal and status, which is not practical
against free-form text.

Set LOG_FORMAT=text for human-readable output when running locally.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.config import get_settings

# LogRecord attributes that are always present. Anything else on a record was
# attached by the caller via `extra=` and is merged into the JSON output.
_STANDARD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "taskName", "thread", "threadName",
})


class JsonFormatter(logging.Formatter):
    """Render each LogRecord as a single-line JSON object."""

    def __init__(self, environment: str) -> None:
        super().__init__()
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "environment": self.environment,
            "message": record.getMessage(),
        }

        # Structured fields passed as logger.info(..., extra={...}).
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # default=str so a stray non-serialisable value degrades to its repr
        # instead of raising inside the logging call.
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """
    Install the root log handler.

    Replaces any handler already present: gunicorn and uvicorn install their own,
    and leaving those attached duplicates every line.
    """
    settings = get_settings()

    handler = logging.StreamHandler()
    if settings.LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter(environment=settings.ENVIRONMENT))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL)

    # uvicorn.access duplicates the richer access log emitted by
    # RequestContextMiddleware, and carries no request id or principal.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error", "gunicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


configure_logging()
logger = logging.getLogger(__name__)
