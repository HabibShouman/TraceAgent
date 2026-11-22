# V9 checks explicit year cutoffs

An exact citation proves that text was retrieved. It can still describe a person who falls outside the requested dates. The completed v4/v8 reviews each found three candidates that failed task requirements even though their answers passed the existing format and citation checks. See the [completed comparison](evidence_v8.md#completed-course-comparison).

V9 recognizes a limited set of name-selection questions starting with “who” or asking for a name, with a single explicit `before YYYY` or `after YYYY` condition in the opening paragraph. The model receives the detected rule and selects supporting excerpts using the existing answer schema. After checking quote membership and page binding, TraceAgent looks for the answer name and one unambiguous year in the same cited sentence or table row. It compares the year strictly with the cutoff. A year equal to the cutoff fails both comparisons.

If evidence is ambiguous, missing, or outside the cutoff, the answer fails with `constraint_error`. The existing correction can use saved observations if a request remains. A failed final request leaves the answer empty. The run record distinguishes a passed citation check from a failed date check. General factual entailment, the person’s role, compound dates, and other filters still require judgment. An unrelated year in the same sentence can be misleading, and a relevant date split across excerpts may require a focused reread.

The year check makes no model requests. Tests use fabricated sources and a mocked SDK transport to verify strict boundaries, mismatched citations, ambiguity, tool-free correction, and exhaustion of the request budget. All 139 offline tests passed. An offline replay rejected the archived v8 candidate that missed the cutoff. The existing benchmark records were preserved.

## Live pilot

The pilot uses a fictional archive supplied in the question and runs one task with a three-request cap. It has no course questions or answer key. In a fresh checkout, prepare it with `uv run python -m examples.prepare_constraint_pilot`. The owner's working copy already has `constraint_pilot_v9` prepared.

```powershell
uv run python -m traceagent eval run --name constraint_pilot_v9 --request-budget 3 --max-tasks 1 --diagnose
```

Review the chosen name, chronology, citations, and request count. A correct output can show that the model followed the instruction on this example. The offline tests cover what happens when the model submits an ineligible answer. A wider live course comparison and official scoring are still pending.
