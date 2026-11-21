"""Prepare one fresh documentation task without model/search requests or keys."""

import argparse
from pathlib import Path

from traceagent.evaluation import EvaluationError, evaluation_path, prepare_evaluation
from traceagent.research import TOOL_AVAILABILITY_VERSION


def prepare_pilot(name: str = "controller_pilot_v5", root: Path | None = None) -> dict:
    if TOOL_AVAILABILITY_VERSION != 1:
        raise EvaluationError("This is the historical v5 pilot. Use python -m examples.prepare_controller_pilot_v6 for the current implementation.")
    return prepare_evaluation(
        evaluation_path(name, root),
        [{
            "task_id": "python-modf-documentation-pilot",
            "question": (
                "Search the official Python documentation and open the entry for math.modf. "
                "What does the first element of its returned pair represent, and what is "
                "the numeric type of both elements? Answer in this form: first element meaning; numeric type."
            ),
            "file_name": "", "level": "development-pilot",
        }],
        model="gemini-3.5-flash-lite", search_backend="serper", max_model_calls=4,
        source_url="local:examples/prepare_controller_pilot.py",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="controller_pilot_v5")
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
