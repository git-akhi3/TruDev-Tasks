import json
import logging
from datetime import datetime, timezone

from .tracing import get_request_id

_SERVICE_NAME = "pulsepay"
_IS_CONFIGURED = False
_RESERVED_LOG_RECORD_KEYS = {
	"args",
	"asctime",
	"created",
	"exc_info",
	"exc_text",
	"filename",
	"funcName",
	"levelname",
	"levelno",
	"lineno",
	"module",
	"msecs",
	"message",
	"msg",
	"name",
	"pathname",
	"process",
	"processName",
	"relativeCreated",
	"stack_info",
	"thread",
	"threadName",
}


class JsonFormatter(logging.Formatter):
	def format(self, record: logging.LogRecord) -> str:
		payload: dict[str, str | int | float | bool | None] = {
			"timestamp": datetime.now(timezone.utc).isoformat(),
			"level": record.levelname,
			"service": _SERVICE_NAME,
			"request_id": get_request_id(),
			"message": record.getMessage(),
		}

		for key, value in record.__dict__.items():
			if key in _RESERVED_LOG_RECORD_KEYS or key.startswith("_"):
				continue
			if key in {"timestamp", "level", "service", "request_id", "message"}:
				continue
			if isinstance(value, (str, int, float, bool)) or value is None:
				payload[key] = value
			else:
				payload[key] = str(value)

		return json.dumps(payload, separators=(",", ":"), ensure_ascii=True)


def _configure_logging() -> None:
	global _IS_CONFIGURED
	if _IS_CONFIGURED:
		return

	handler = logging.StreamHandler()
	handler.setFormatter(JsonFormatter())

	root_logger = logging.getLogger()
	root_logger.handlers.clear()
	root_logger.addHandler(handler)
	root_logger.setLevel(logging.INFO)

	_IS_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
	_configure_logging()
	return logging.getLogger(name)
