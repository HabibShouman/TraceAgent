"""Prepare a citation-interface comparison without credentials or API calls."""

import argparse
from pathlib import Path

from traceagent.evaluation import EvaluationError, evaluation_path, prepare_evaluation


def prepare_pilot(name: str = "evidence_pilot_v7", root: Path | None = None) -> dict:
    return prepare_evaluation(
        evaluation_path(name, root),
        [{
            "task_id": "python-frexp-documentation-pilot",
            "question": (
                "Search and open the official Python math documentation for math.frexp. "
                "What are the numeric types of the two components in its returned pair, "
                "in return order? Give only the two type names as a comma-separated list."
            ),
            "file_name": "", "level": "development-pilot",
        }],
        model="gemini-3.5-flash-lite", search_backend="serper", max_model_calls=4,
        source_url="local:examples/prepare_evidence_pilot.py",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="evidence_pilot_v7")
    args = parser.parse_args()
    try:
        prepare_pilot(args.name)
    except EvaluationError as error:
        print(str(error))
        return 2
    print(f"Prepared {args.name}: one documentation comparison, up to four model requests. No API request was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
