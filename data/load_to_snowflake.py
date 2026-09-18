"""Load generated banking CSV files into Snowflake.

TODO: Implement staging, COPY INTO, validation, and idempotent load behavior.
"""

from pathlib import Path

from src.services.snowflake_client import SnowflakeClient


def load(input_dir: Path, client: SnowflakeClient | None = None) -> None:
    """Declare the loader interface without changing Snowflake state.

    TODO: Upload CSVs to a named stage and load each target table safely.
    """

    _ = (input_dir, client)
    print("TODO: implement CSV loading into Snowflake")


if __name__ == "__main__":
    load(Path(__file__).parent / "generated")
