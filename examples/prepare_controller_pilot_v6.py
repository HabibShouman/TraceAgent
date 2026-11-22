"""Prepare a fresh four-request documentation pilot without API calls or keys."""

import argparse
from pathlib import Path

from traceagent.evaluation import EvaluationError, evaluation_path, prepare_evaluation
from traceagent.evidence import EVIDENCE_VERSION


def prepare_pilot(name: str = "controller_pilot_v6", root: Path | None = None) -> dict:
    if EVIDENCE_VERSION != 0:
        raise EvaluationError("This is the historical v6 pilot. Use python -m examples.prepare_evidence_pilot for the current implementation.")
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
        source_url="local:examples/prepare_controller_pilot_v6.py",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="controller_pilot_v6")
    args = parser.parse_args()
    try:
        prepare_pilot(args.name)
    except EvaluationError as error:
        print(str(error))
        return 2
    print(f"Prepared {args.name}: one fresh task, up to four model requests. No API request was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
