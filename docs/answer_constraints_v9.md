# V9 checks explicit year cutoffs

An exact citation proves that text was retrieved. It can still describe a person who falls outside the requested dates. The completed v4/v8 reviews each found three candidates that failed task requirements even though their answers passed the existing format and citation checks. See the [completed comparison](evidence_v8.md#completed-course-comparison).

V9 recognizes a limited set of name-selection questions starting with “who” or asking for a name, with a single explicit `before YYYY` or `after YYYY` condition in the opening paragraph. The model receives the detected rule and selects supporting excerpts using the existing answer schema. After checking quote membership and page binding, TraceAgent looks for the answer name and one unambiguous year in the same cited sentence or table row. It compares the year strictly with the cutoff. A year equal to the cutoff fails both comparisons.

If evidence is ambiguous, missing, or outside the cutoff, the answer fails with `constraint_error`. The existing correction can use saved observations if a request remains. A failed final request leaves the answer empty. The run record distinguishes a passed citation check from a failed date check. General factual entailment, the person’s role, compound dates, and other filters still require judgment. An unrelated year in the same sentence can be misleading, and a relevant date split across excerpts may require a focused reread.

The year check makes no model requests. Tests use fabricated sources and a mocked SDK transport to verify strict boundaries, mismatched citations, ambiguity, tool-free correction, and exhaustion of the request budget. All 139 offline tests passed. An offline replay rejected the archived v8 candidate that missed the cutoff. The existing benchmark records were preserved.

## Live pilot

The fictional archive pilot passed on its first request. The answer named the only person who won after the cutoff, and its supplied-input excerpt contained the supporting sentence. The citation and year checks both passed. The run used one model request, 1,687 reported tokens, and no tools or corrections.

The check recognizes one of the 13 supported text questions in the course snapshot. The pilot verifies the normal live acceptance path for one example. Offline tests cover the correction path. A wider course comparison and official scoring are pending.

For reproduction on a fresh checkout, prepare the fictional one-task profile with `uv run python -m examples.prepare_constraint_pilot`, then run it with a three-request cap:

```powershell
uv run python -m traceagent eval run --name constraint_pilot_v9 --request-budget 3 --max-tasks 1 --diagnose
```

The original pilot is complete and can be inspected with `uv run python -m traceagent eval status --name constraint_pilot_v9`.
