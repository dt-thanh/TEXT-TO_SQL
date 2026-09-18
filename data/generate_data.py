"""Generate fake banking CSV data with Faker and pandas.

TODO: Implement deterministic star-schema generation and referential integrity.
"""

from pathlib import Path

import pandas as pd
from faker import Faker


def generate(output_dir: Path, rows: int = 1_000, seed: int = 42) -> None:
    """Declare the fake-data generator contract without writing datasets yet.

    TODO: Generate all dimensions and facts, then save one CSV per table.
    """

    _ = (output_dir, rows, seed, pd, Faker)
    print("TODO: implement fake banking star-schema generation")


if __name__ == "__main__":
    generate(Path(__file__).parent / "generated")
