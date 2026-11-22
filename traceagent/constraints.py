"""Narrow, deterministic checks for explicit year cutoffs on named answers."""

from dataclasses import dataclass
import re


ANSWER_CONSTRAINT_VERSION = 1
_NAME_QUESTION = re.compile(
    r"^(?:who\b|what (?:is|was) the (?:(?:first|last|full) )?name\b)", re.I,
)
_YEAR_BOUND = re.compile(r"\b(before|after) ([1-9][0-9]{3})\b(?![-/.][0-9]| (?:BC|BCE)\b)", re.I)
_YEAR = re.compile(r"\b[1-9][0-9]{3}\b")
_CLAUSE_BOUNDARY = re.compile(r"\|\s*\||[.!?;]\s+(?=[A-Z])")


@dataclass(frozen=True)
class NameYearBound:
    direction: str
    year: int

    def model_instruction(self) -> str:
        return (
            f"The selected person's relevant event must be strictly {self.direction} "
            f"{self.year}. Cite a short span with the answer name and its single "
            "event year together in the same sentence or table row. Check the "
            "person's role and the other requirements before writing the answer."
        )

    def error(self, answer: str, evidence: list[dict]) -> str:
        """Check a year only when a cited segment contains the submitted name."""
        name = re.compile(rf"(?<!\w){re.escape(answer.casefold())}(?!\w)")
        years = set()
        ambiguous = False
        for citation in evidence:
            for segment in _CLAUSE_BOUNDARY.split(citation["quote"]):
                if not name.search(segment.casefold()):
                    continue
                segment_years = {int(year) for year in _YEAR.findall(segment)}
                ambiguous |= len(segment_years) > 1
                years.update(segment_years)
        if ambiguous or len(years) != 1:
            return (
                "The cited evidence does not connect the answer name to one clear "
                f"event year. Cite a single-year sentence or row that shows the name "
                f"and a year strictly {self.direction} {self.year}."
            )
        year = next(iter(years))
        if (self.direction == "after" and year <= self.year) or (
            self.direction == "before" and year >= self.year
        ):
            return (
                f"The cited year {year} does not satisfy the required cutoff "
                f"({self.direction} {self.year}). Select an eligible answer from "
                "the retained evidence, or return unresolved."
            )
        return ""


def name_year_bound(question: str) -> NameYearBound | None:
    """Recognize a single explicit before/after year on a name-selection task."""
    # Limit deterministic enforcement to a narrow form. Compound and
    # date-qualified requests should go through the ordinary review.
    instructions = re.split(r"\r?\n[ \t]*\r?\n", question, maxsplit=1)[0]
    instructions = " ".join(instructions.split())
    if not _NAME_QUESTION.match(instructions) or len(_YEAR.findall(instructions)) != 1:
        return None
    match = _YEAR_BOUND.search(instructions)
    if match is None:
        return None
    direction, year = match.groups()
    return NameYearBound(direction.casefold(), int(year))
