# V4 baseline review

Reviewed 2026-11-18. All tasks have reached a terminal routing/result state under the unchanged v4 profile. Official exact-match accuracy has not been measured. This is the Agents Course's public 20-question validation subset, not the full GAIA benchmark.

## Outcome

| Result | Tasks | Interpretation |
| --- | ---: | --- |
| Generated candidates | 8 | Passed implemented format/quote checks; correctness remains ungraded |
| Unresolved | 5 | No accepted answer within the fixed policy and budget |
| Unsupported | 7 | Five attachment inputs and two video inputs lack readers |
| Pending | 0 | No further v4 run is needed |

Eight candidates cover 40% of the twenty-task answer slots. That percentage is **answer coverage, not accuracy**. Two candidates have identified reasoning errors, and other candidates retain comparison or multi-hop evidence gaps. No course pass or certificate result is established. All twenty tasks remain in the scoring denominator.

The profile uses Gemini 3.5 Flash-Lite, Serper, at most eight model requests per task attempt, twelve tool calls, four searches, and one final-answer correction. It reserves the last permitted model request for schema-constrained answering without tools. No provider retries, paid fallback, or automatic model switch were introduced.

## Recorded usage

| Metric | Total |
| --- | ---: |
| Task attempts / sessions | 15 / 15 |
| Model-request reservations | 79 |
| Successful model responses | 77 |
| Failed or setup-error reservations | 2 |
| Tool calls | 61 |
| Actual search requests | 37 |
| Search-tool calls after exhaustion | 8 |
| Read-tool calls | 15 |
| Answer corrections | 3 |
| Reserved finalization responses | 5 |
| Reported input / total tokens | 241,615 / 247,324 |
| Sum of saved attempt elapsed times | 216.708 seconds |

Elapsed time is the sum recorded by individual attempts, excluding pauses between sessions. It is not the calendar duration or a general latency benchmark. Failed requests and prior provider errors remain in the history. The [machine-readable summary](../examples/evaluation_v4_completed_summary.json) includes profile and implementation fingerprints without benchmark questions or answers.

## What worked

- Task-level resume retained completed results and prior failed attempts without rewriting candidates.
- Request accounting included provider failures, and the controller finalized within its fixed limits.
- Three answer corrections passed the local checks after shortening or correcting evidence. Passed checks did not guarantee correct reasoning.
- Evidence checks rejected invented source IDs and quotations absent from opened passages.
- Several candidates have directly matching retrieved quotations, including institutional bibliography and competition-table evidence in later tasks.

## What failed and why it matters

| Observation | Design implication |
| --- | --- |
| The model requested an exhausted search tool eight times | A prompt and a rejecting tool wrapper do not prevent wasted model turns; tool availability should reflect remaining resources |
| Relevant URLs were returned but not opened, or were opened late | Research needs stronger control over the transition from discovery to reading |
| HTTP refusal, a CAPTCHA page, and incomplete excerpts obstructed retrieval | A successful HTTP/read operation does not establish that useful source content was obtained |
| A matching quote supported one fact without establishing a tie-break or every link in a multi-hop chain | Provenance checks must be distinguished from evidence completeness and factual correctness |
| Two self-contained candidates passed checks despite reasoning errors | Better tool control alone will not fix instruction interpretation or final-answer consistency |
| Seven inputs were unsupported | Reader coverage is a separate source of failure that more web searches cannot solve |

One later corrected candidate used an official institutional bibliography. Another established an individual participation count without fully establishing the requested alphabetical tie-break. A historical-roster task searched with an unverified number that appeared under a statistics-table column; it never opened a roster. The final task returned a matching competition-table quote and the requested first-name format, although the historical status of the recorded country was not separately sourced within the run. Original answers and unresolved results remain unchanged.

## Evaluation limits

The overall manifest still reports `not_audited`: individual offline reviews are limited observations, not a claim of complete source independence. Two unresolved tasks received unopened agent-research snippets containing related task guidance or paraphrased goals. Neither produced an accepted answer. Source filtering also blocked sixteen observations, but this does not establish universal leakage prevention; it can miss paraphrases or reject useful material.

This is development on a public validation subset. Future comparisons must disclose that history and include fresh, independently checked questions. No benchmark solution list, manually corrected answer, or selected successful rerun has been inserted into the export. Official scoring, a model-only comparison, a public Space, and the recruiter-facing demonstration remain pending.

## Next design iteration

Start with controller behavior while retaining the current model and numerical limits. Remove exhausted tools from model declarations and favor reading available search results before spending more requests on discovery. Keep execution-time guards as a second boundary. Preserve v4 as the reference result; changed code requires a separate evaluation profile.

Verify this change first on fabricated tasks with known facts, including an exhausted search allowance, an unread useful URL, a blocked page, and insufficient evidence. Measure whether it reduces wasted actions without forcing unsupported answers. Then run a small explicit-budget pilot before another full public-subset evaluation. An improvement in accuracy must be measured, not inferred from cleaner traces.

Subsequent work should handle challenge pages and incomplete passages, strengthen evidence coverage and final-answer consistency, and add attachment readers. A model-only comparison and fresh reasoning cases should help distinguish controller failures from model reasoning limits. Each intervention should have a clear hypothesis and a separate result record.
