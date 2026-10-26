"""Project-wide exception hierarchy."""


class FinSightError(Exception):
    """Base class for every error raised by FinSight code."""


class ConfigError(FinSightError):
    """A required setting is missing or invalid."""


class WarehouseError(FinSightError):
    """Connecting to or querying Snowflake failed."""


class SourceAPIError(FinSightError):
    """An external data source (Binance, FRED) failed or returned unusable data."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        # Set when the source answered with an HTTP error that is not worth retrying.
        self.status_code = status_code


class LLMError(FinSightError):
    """The language model call failed or returned something unusable."""
