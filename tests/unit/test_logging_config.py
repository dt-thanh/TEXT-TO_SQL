"""Unit tests for logging setup."""

import logging
import time
from collections.abc import Iterator

import pytest

from src.common.logging_config import HANDLER_NAME, NOISY_LOGGERS, setup_logging


@pytest.fixture(autouse=True)
def restore_loggers() -> Iterator[None]:
    """Undo whatever setup_logging does so other tests are not affected."""

    root = logging.getLogger()
    old_level, old_handlers = root.level, list(root.handlers)
    old_noisy_levels = {name: logging.getLogger(name).level for name in NOISY_LOGGERS}
    yield
    root.setLevel(old_level)
    root.handlers = old_handlers
    for name, level in old_noisy_levels.items():
        logging.getLogger(name).setLevel(level)


def our_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if h.get_name() == HANDLER_NAME]


def test_setup_logging_is_idempotent() -> None:
    setup_logging("INFO")
    setup_logging("DEBUG")

    assert len(our_handlers()) == 1
    assert logging.getLogger().level == logging.DEBUG


def test_timestamps_are_utc() -> None:
    setup_logging("INFO")

    assert our_handlers()[0].formatter.converter is time.gmtime


@pytest.mark.parametrize("name", ["httpx", "snowflake.connector"])
def test_per_request_library_logs_are_quiet(name: str) -> None:
    setup_logging("INFO")

    assert logging.getLogger(name).level == logging.WARNING
