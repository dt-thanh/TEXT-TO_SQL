"""Project-wide exception hierarchy."""


class FinSightError(Exception):
    """Base class for every error raised by FinSight code."""


class ConfigError(FinSightError):
    """A required setting is missing or invalid."""


class WarehouseError(FinSightError):
    """Connecting to or querying Snowflake failed."""


class SourceAPIError(FinSightError):
    """An external data source (Binance, FRED) failed or returned unusable data."""


class LLMError(FinSightError):
    """The language model call failed or returned something unusable."""
