"""Configure process-wide logging once, at the program entrypoint."""

import logging
import time

HANDLER_NAME = "finsight"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def setup_logging(level: str = "INFO") -> None:
    """Send logs to stderr with UTC timestamps; safe to call more than once."""

    root = logging.getLogger()
    root.setLevel(level)
    if any(handler.get_name() == HANDLER_NAME for handler in root.handlers):
        return

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    formatter.converter = time.gmtime
    handler = logging.StreamHandler()
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(formatter)
    root.addHandler(handler)
