"""Prepare a fictional, one-request pilot of the retained-text quote format."""

import argparse
from pathlib import Path

from traceagent.constraints import ANSWER_CONSTRAINT_VERSION
from traceagent.evaluation import EvaluationError, evaluation_path, prepare_evaluation
from traceagent.evidence import EVIDENCE_VERSION


def prepare_pilot(name: str = "quote_fallback_pilot_v10", root: Path | None = None) -> dict:
    if EVIDENCE_VERSION != 3 or ANSWER_CONSTRAINT_VERSION != 1:
        raise EvaluationError("Use the original v10 implementation for this pilot.")
    inventory = "\n".join(
        f"Inventory entry {i:03d}. The storage location is pending review."
        for i in range(1, 41)
    )
    return prepare_evaluation(
        evaluation_path(name, root),
        [{
            "task_id": "fictional-inventory-retained-quote",
            "question": (
                "Which town stores the Atlas Loom? Use only the supplied fictional inventory. "
                "Give only the town name, and cite the short sentence that establishes the location.\n\n"
                f"Inventory:\n{inventory}\nThe Atlas Loom is stored in Alderwick."
            ),
            "file_name": "",
            "level": "development-pilot",
        }],
        max_model_calls=1,
        source_url="local:examples/prepare_quote_fallback_pilot.py",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="quote_fallback_pilot_v10")
    args = parser.parse_args()
    try:
        prepare_pilot(args.name)
    except EvaluationError as error:
        print(str(error))
        return 2
    print(f"Prepared {args.name} with one supplied-input task and a one-request cap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
