"""Project-wide exception hierarchy."""


class FinSightError(Exception):
    """Base class for every error raised by FinSight code."""


class ConfigError(FinSightError):
    """A required setting is missing or invalid."""


class WarehouseError(FinSightError):
    """Connecting to or querying Snowflake failed."""
