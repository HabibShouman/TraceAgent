# V8: retain reading context alongside citation IDs

Implemented 2026-11-22 after reviewing the completed nonbenchmark v7 pilot. That run returned a correct type pair within four model requests, selected a registered ID, and passed exact-text validation without a correction. Its selected quotation only identified the returned pair; it did not establish the requested types. The full retained source did contain the type explanation, but the 32-entry catalog exposed to the model omitted it. The original candidate, state, and records remain unchanged. See the [pilot review](../examples/evidence_v7_live_pilot_review.json).

## What changes

Reading context and citation choices have different purposes. The model now receives the reader's existing bounded `passages` as well as its registered `excerpts`, source metadata, notices, and outgoing links. Passages provide context for reasoning. Excerpt IDs provide exact text that can be cited without asking the model to rewrite it.

If a passage contains a needed fact but the catalog omits its supporting words, the model can call `read_url` on the same URL with a more specific focus. The existing document cache avoids another download. The reread still consumes a tool call and usually another model turn; recovery is subject to the original limits. The instruction recommends this route instead of searching again for the same document. It does not force a particular action or guarantee a successful live recovery.

The catalog still has at most 32 excerpts of ten words and 240 characters each. Exact source membership, registered-page binding, and the combined 25-word limit per URL remain unchanged. A citation can pass these checks without supporting the answer. Semantic support and reasoning still need separate review.

## Pilot observations and limits

| V7 observation | Result |
| --- | --- |
| Model requests / tool calls | 4 / 3 |
| Search requests | 2, including one failed request |
| Final-answer corrections | 0 |
| Input / total tokens | 10,816 / 10,989 |
| Recorded run time | 11.975 seconds |
| Registered ID and exact text | Passed |
| Answer compared with retained definition | Consistent |
| Selected excerpt establishes the types | No |

The second search reached Serper and returned HTTP 400. This was a provider rejection, not a controller denial or an exhausted four-search allowance. The saved record does not establish the provider's reason. The run used existing evidence in its reserved final request, with no automatic retry or fallback.

The live pilot establishes that the registered-ID interface can operate. It does not establish complete evidence quality, an accuracy gain, or a GAIA result. It is a development question already used in v6, not a held-out performance estimate.

## Verification

All 134 offline tests pass. A new SDK transport regression uses a fabricated sensor report whose required fact is absent from its first catalog. It checks that the full retained passage reaches the model, a scripted focused reread exposes a suitable registered span, the final answer passes strict validation, and only one source download occurs. These scripted responses test the available recovery path, not live model planning. Other tests retain citation, budget, protocol, source-screening, redaction, and snapshot guards. Historical v7 preparation now refuses to create a misleading old-version profile under changed code.

Offline inspection also confirms that the passages restored from the actual v7 source include the omitted explanation. The original saved source and candidate are not rewritten. Restoring passages increases model input context compared with v7's compact observation; actual token usage and planning quality need measurement.

## Next course run

`gaia_evidence_v8` is prepared in the owner's working project from the existing question-only 20-task snapshot. It has 13 pending text tasks, seven unsupported inputs, and zero requests. No previous answers or tool observations are supplied. The [preparation summary](../examples/evidence_v8_prepared_summary.json) records the dataset, profile, and implementation fingerprints.

```powershell
uv run python -m traceagent eval run --name gaia_evidence_v8 --request-budget 8 --max-tasks 1 --diagnose
```

Keep this configuration fixed while processing supported tasks. Collect results and failure categories before another global revision; retain original outputs for grading. The same Gemini model, Serper backend, eight-model-request/twelve-tool/four-search limits, and one optional correction remain. No live model or search calls were made during this revision. V4, partial v5, and the v6/v7 pilots remain preserved. Official scoring, the two previously identified reasoning errors, broader input readers, model-only comparison, and the public demonstration remain separate work.
