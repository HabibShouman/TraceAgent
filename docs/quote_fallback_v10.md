# V10 can cite retained text directly

The v8 review found an answer whose supporting words were in an opened source but outside the 32-entry citation catalog. The model returned a nonexistent excerpt ID in its correction, so TraceAgent recorded an unresolved result. See the [completed comparison](evidence_v8.md#completed-course-comparison).

V10 offers two citation forms in the final and correction responses. Each entry gives a source ID with either a registered excerpt ID or a short verbatim quote from that source's retained text. The model should prefer registered IDs and use the quote form when the catalog omitted a needed span. Local validation rejects an entry with both forms or neither.

Both forms use the same source membership check, with Unicode and whitespace normalization. The program rejects unknown sources, unregistered IDs, paraphrases, and text made discontinuous by inserted ellipses. Across all citations to the same URL, the total limit is 25 quoted words. Registered PDF excerpts retain their page binding. The literal form receives the first retained page on which the span matches. The [v9 cutoff check](answer_constraints_v9.md) still applies to either form for supported name questions. Factual support for claims beyond that check still needs review.

All 140 offline tests pass. The mocked SDK sends a retained passage containing a fact omitted by the catalog and exercises both routes that disable tools. The last available request can return a quote directly. An earlier invalid citation can also use a quote in its existing correction request. An offline replay with the archived benchmark passage verified that an available verbatim quote would pass membership. The archived result and answer remain intact.

## Live pilot

The fictional inventory pilot deliberately places a needed fact beyond the supplied-input citation catalog. Its one model request uses the structured final response with tools disabled. This checks whether the provider and model can use the quote field end to end. The offline tests cover the opened-source equivalent.

The owner's working copy already has `quote_fallback_pilot_v10` prepared. In a fresh checkout, prepare it with `uv run python -m examples.prepare_quote_fallback_pilot`.

```powershell
uv run python -m traceagent eval run --name quote_fallback_pilot_v10 --request-budget 1 --max-tasks 1 --diagnose
```

The pilot should return the town only and an exact quote that supports it. Completion on this fictional input will be checked separately from any course run.
