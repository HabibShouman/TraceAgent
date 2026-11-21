# V7: select registered evidence instead of rewriting quotations

Implemented 2026-11-21. The v6 documentation pilot found the needed definition and returned a supported candidate answer, but neither evidence check passed: the initial quotation exceeded 25 words, and the correction inserted an ellipsis. The original unresolved result and empty export remain preserved. The [failure review](../examples/controller_v6_pilot_failure.json) records the diagnosis without accepting that failed response.

## Division of work

| Component | Responsibility |
| --- | --- |
| Reader | Retain the source passages and register bounded exact excerpts with IDs and page references |
| Model | Select the excerpts that support its proposed answer |
| Validator | Resolve IDs, recheck source membership/page, and enforce the combined quotation limit |
| Formatter | Render the registered text as the supporting quotation |

For example, the model can return `{"source_id":"S1","excerpt_id":"S1-E3"}`. The program resolves the text; it does not ask the model to copy or shorten it. Registered excerpts are normalized only for Unicode/whitespace, using the same membership convention as literal quotations.

## Bounds and integrity

Each source has at most 32 registered excerpts, each at most ten words and 240 characters. Windows near the requested focus are prioritized. Supplied-input evidence has its own Q1 catalog, explicitly labeled as question data rather than independent external facts.

The model receives the excerpt catalog, source metadata, focus/truncation notices, and outgoing links. Full retained passages remain in the private run record instead of being repeatedly sent as tool observations. Outgoing document links remain available; the new view does not shorten the reader's existing link list.

An ID must belong to the claimed source. The resolved text must still occur in a retained passage, and PDF page references must agree with the registered excerpt. All selected text from the same URL, including different focused reads, remains limited to 25 words total. Ten-word excerpts normally allow two selections per URL. An unknown ID, a mismatched source, rewritten text alongside an ID, altered registry text, or excessive combined quoting is rejected.

Historical exact literal quotations remain supported by the validator. Ellipses and paraphrases are still rejected when they do not match the source. The current final/correction JSON schema asks for IDs; it does not relax membership checking. No failed historical candidate is automatically converted into an accepted answer.

## Verification and limitations

132 offline tests pass locally, including ten excerpt-specific cases and a guard against preparing the historical v6 fixture under changed code. Real SDK calls over mocked HTTP verify registered-ID answers, correction without new tools, matching function-response IDs/signatures, compact observations, and full retained source records. Tests also cover unknown/cross-source IDs, tampering, shared-URL word limits, repeated text on different PDF pages, outgoing links, bounded catalogs, and short Q1 input.

Offline inspection of the failed v6 document confirms that the catalog contains the two needed type spans. Selecting those IDs can pass strict membership while the original ellipsis quotation remains invalid. That inspection is not a model run, a submitted answer, or an accuracy result.

A valid ID still does not prove that an excerpt entails the answer. Bounded excerpts may omit conditions or context, and the model may need a focused reread. The two earlier reasoning errors remain unresolved. Search-result quality, missing input readers, model-only comparison, public Space/demo, and official grading remain separate work. No live citation-selection or accuracy improvement has been measured yet.

## Four-request comparison

This pilot reuses the same nonbenchmark documentation question as v6. It starts without prior answers or observations and uses the same model, search policy, and four-request cap. Preparation is offline:

```powershell
uv run python -m examples.prepare_evidence_pilot
```

The owner's working project already has it prepared. Run once:

```powershell
uv run python -m traceagent eval run --name evidence_pilot_v7 --request-budget 4 --max-tasks 1 --diagnose
```

The [preparation summary](../examples/evidence_v7_prepared_summary.json) records zero live attempts and the new fingerprint. The v6 search-recovery policy is retained; this revision changes evidence production and model observations. The standard research budgets remain unchanged and no provider retry or paid fallback was added. Earlier checkpoints remain readable but cannot be resumed using changed code. The default name for a later course profile is `gaia_evidence_v7`; no full course run has been started under it.
