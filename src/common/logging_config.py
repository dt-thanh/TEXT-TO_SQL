"""Configure process-wide logging once, at the program entrypoint.

Every line carries the id of the request it belongs to ("-" outside a request). LOG_FORMAT=json
writes one JSON object per line instead, for a log collector.
"""

import json
import logging
import time

from src.common.request_context import request_id_var

HANDLER_NAME = "finsight"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(request_id)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Libraries that log every request or connection at INFO. Our own clients log what matters.
NOISY_LOGGERS = ("httpx", "snowflake.connector")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": time.strftime(DATE_FORMAT, time.gmtime(record.created)),
            "level": record.levelname,
            "request_id": getattr(record, "request_id", "-"),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Send logs to stderr with UTC timestamps; safe to call more than once."""

    root = logging.getLogger()
    root.setLevel(level)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if any(handler.get_name() == HANDLER_NAME for handler in root.handlers):
        return

    if fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
        formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
