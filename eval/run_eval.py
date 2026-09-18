"""Evaluate execution accuracy against gold SQL result sets.

TODO: Run generated and gold queries and compare normalized, order-aware results.
"""

from pathlib import Path


def run(dataset_path: Path, results_dir: Path) -> None:
    """Declare the evaluation runner without calling external systems.

    TODO: Add graph invocation, safe Snowflake execution, metrics, and JSON reports.
    """

    _ = (dataset_path, results_dir)
    print("TODO: implement execution-accuracy evaluation")


if __name__ == "__main__":
    base_dir = Path(__file__).parent
    run(base_dir / "gold_questions.jsonl", base_dir / "results")
