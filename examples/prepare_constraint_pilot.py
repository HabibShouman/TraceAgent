"""Prepare a fictional archive question without credentials or API calls."""

import argparse
from pathlib import Path

from traceagent.constraints import ANSWER_CONSTRAINT_VERSION
from traceagent.evidence import EVIDENCE_VERSION
from traceagent.evaluation import EvaluationError, evaluation_path, prepare_evaluation


def prepare_pilot(name: str = "constraint_pilot_v9", root: Path | None = None) -> dict:
    if ANSWER_CONSTRAINT_VERSION != 1 or EVIDENCE_VERSION != 2:
        raise EvaluationError("Use the original v9 implementation for this pilot.")
    return prepare_evaluation(
        evaluation_path(name, root),
        [{
            "task_id": "northbank-medal-year-cutoff",
            "question": (
                "What is the first name of the person who won the Northbank medal after 2015? "
                "Use only the supplied archive. Give only the first name.\n\n"
                "Archive:\nArden won in 2012.\nDana won in 2015.\n"
                "Perry entered in 2021.\nJules won in 2018."
            ),
            "file_name": "",
            "level": "development-pilot",
        }],
        max_model_calls=3,
        source_url="local:examples/prepare_constraint_pilot.py",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="constraint_pilot_v9")
    args = parser.parse_args()
    try:
        prepare_pilot(args.name)
    except EvaluationError as error:
        print(str(error))
        return 2
    print(f"Prepared {args.name} with one supplied-input task and a three-request cap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
