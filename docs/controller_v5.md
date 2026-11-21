# V5: tools available for the current state

Implemented 2026-11-21. V4 recorded eight search-tool attempts after the search allowance was exhausted, plus repeated discovery before reading returned URLs. V5 changes controller behavior while retaining the model, source filters, quotation checks, and standard research limits. Accuracy improvement has not been measured.

## Design

The model chooses an action from the functions declared for its current request. The controller determines which functions are available. Discovery, reading, arithmetic, and answering remain distinct actions.

| Research state | Search available? | Reading / arithmetic | Answering |
| --- | --- | --- | --- |
| Search allowance remains; no pending read | Yes | Available | May answer or report unresolved |
| Search returned usable URLs | Paused until a valid URL/focus read attempt | Available | May answer or report unresolved |
| Four search requests consumed | Removed for the rest of this run | Available | May answer or report unresolved |
| Reserved final request or answer correction | No tools | No tools | Finish from retained evidence |

Empty or fully filtered search results leave discovery available while allowance remains. A valid read attempt releases the pause even if fetching or parsing fails, allowing a new search for alternatives. Invalid URL/focus arguments do not release it. A read attempt need not establish that the page is relevant or complete; that remains an evidence-selection limitation. Re-reading cached content can release a pause without adding new information.

Execution checks complement the declarations. A model can still request a hidden function, and one model response can contain several calls. The graph checks both the functions advertised for that response and the current policy before each execution. A disallowed call produces `tool_unavailable`, consumes a tool-action slot, and makes no search-provider request. Existing request/tool limits still end a model that ignores the available choices. This reduces opportunities for wasted actions; it cannot guarantee obedience or correctness.

Each model-response record now includes `available_tools` and `tool_restrictions`. Policy reasons distinguish `read_before_search` from `search_budget`. Function-response IDs, original model content, and thought signatures are retained for the SDK protocol; internal model messages remain excluded from saved run records.

## Verification

118 offline tests pass locally. Nine new availability tests use fabricated reports and the real SDK over mocked HTTP transport where applicable. They verify search removal after exhaustion, search/read/answer declaration changes, recovery after HTTP 403, no forced answer when evidence is insufficient, empty/filtered results, invalid reads, batched searches, ignored declarations, and serialization when no tool is available. A tenth new test checks the pilot's local provenance, four-request limit, policy metadata, and refusal to overwrite it.

These tests validate enforcement and protocol behavior, not live model planning or an accuracy improvement. No paid service, extra model, transport retry, automatic fallback, or larger benchmark allowance was added.

## First live pilot

Use one fresh question about Python's `math.modf` documentation, outside the GAIA subset. Preparation saves the question and profile locally without reading credentials or contacting a service:

```powershell
uv run python -m examples.prepare_controller_pilot
```

The owner's working project already has this pilot prepared. Inspect or run it:

```powershell
uv run python -m traceagent eval status --name controller_pilot_v5
uv run python -m traceagent eval run --name controller_pilot_v5 --request-budget 4 --max-tasks 1 --diagnose
```

The saved profile selects Gemini 3.5 Flash-Lite / Serper and permits at most four model requests, including correction/finalization. A useful run should open the official documentation after discovery, avoid further search while paused, and produce supported evidence or an explicit unresolved result. Review the actual trace before any further live test. This one case does not establish a general improvement. The [pilot preparation summary](../examples/controller_v5_prepared_summary.json) contains zero live attempts; the question source is labeled local rather than the course endpoint.

## Observed first live pilot

The owner-run pilot completed with one accepted candidate using four model requests, two tool calls (one search and one focused read), one answer correction, 13,781 input tokens, 14,040 total tokens, and 10.01 seconds. Review confirmed that search was omitted from the second request's declarations and restored after the read. The initial final response failed quote membership; its one permitted correction returned an 18-word quote exactly matching the retained official documentation. The final answer follows the requested format and is supported by that definition. The whole-page excerpt was truncated, but the relevant definition was retained.

Only the corrected final candidate is archived, so the precise wording of the earlier invalid quotation is not established. Search exhaustion was not exercised live in this case; it remains covered by offline tests. This is one integration observation rather than a measured improvement against v4 or a GAIA result. The [live pilot summary](../examples/controller_v5_live_pilot_summary.json) separates observed mechanisms from remaining limits.

The working project now has `gaia_controller_v5` prepared from v4's identical question-only snapshot, without previous candidates or observations: thirteen pending tasks, seven unsupported inputs, and zero requests. Run one comparison task with the original eight-request ceiling:

```powershell
uv run python -m traceagent eval run --name gaia_controller_v5 --request-budget 8 --max-tasks 1 --diagnose
```

Review that task's actual actions and evidence before choosing another batch. The completed fresh pilot stays separate from course scoring.

## First course comparison task

The first v5 course task returned the same ungraded candidate as v4. The question snapshot, selected model, search backend, numerical limits, and source-filter version match; controller policy and its associated prompt instructions differ. The opened encyclopedia quote matches the retained table, and returned search observations were Wikipedia pages without observed task-specific walkthrough or answer-key wording. The whole-page excerpt is truncated; official correctness remains unmeasured.

| Recorded metric | V4 | V5 |
| --- | ---: | ---: |
| Model requests | 6 | 5 |
| Actual search-provider requests | 4 | 1 |
| Successful source reads | 1 | 1 |
| Denied search attempts | 0 | 2 |
| Reported total tokens | 15,438 | 11,515 |

Both denied searches came from separate model responses after search had been omitted from the declarations. The guard therefore protected provider access but did not eliminate wasted model turns. The model then read the returned URL and answered without a correction or reserved finalization. The [curated comparison](../examples/evaluation_v5_first_comparison.json) preserves these observations without the question or candidate answer.

One repeated public-validation task does not establish an average or causal improvement. Search results and provider timing can vary across dates. Keep the implementation fixed and inspect different tasks before drawing broader conclusions. V5 now has one generated candidate, twelve pending tasks, and seven unsupported inputs after five requests; v4 remains unchanged.

## First three matched tasks: mixed effects

The self-contained second task finished in one request with no tools or correction, compared with two requests and one quote correction in v4. It repeats the same reasoning error: an additional output transformation not requested by the input. Matching Q1 evidence and parseable JSON do not establish correct interpretation. Its original candidate remains preserved, with a separate manual flag.

The third task followed search/read alternation without any denied calls. It used four searches and three reads before reserved finalization. Both final quotations match the archive and together cover attribution and promotion date within the quotation limit. Another candidate archive has a promotion date outside the requested month. The monthly roundup missed its focus term, and the three retained excerpts are truncated, so exhaustive uniqueness is not established. Returned search observations and opened sources were Wikipedia pages without observed task-specific walkthrough or answer-key wording.

For that third task, v5 used eight requests and 64,926 reported total tokens; v4 used seven requests and 31,462 tokens. More source passages remained in subsequent request history. The final candidate is unchanged.

| Aggregate over the first three matched tasks | V4 | V5 |
| --- | ---: | ---: |
| Model requests | 15 | 14 |
| Actual search-provider requests | 8 | 5 |
| Successful source reads | 3 | 4 |
| Reported total tokens | 48,961 | 77,604 |
| Identified reasoning errors in these candidates | 1 | 1 |

The [three-task review](../examples/evaluation_v5_three_task_review.json) separates these observations from accuracy claims. All three candidates are unchanged. Provider results, response choices, and dates differ, and this small public-validation sample is insufficient to establish an aggregate or causal gain. The controller enforces execution boundaries and exposes a source-context tradeoff; it does not solve reasoning or guarantee efficient choices.

V5 now has three generated candidates, ten pending tasks, and seven unsupported inputs after fourteen reservations. Keep its implementation fixed for further bounded comparisons. Smaller relevant passages, stopping once evidence is sufficient, and instruction/answer consistency remain separate future improvement targets. Original v4/v5 candidates and usage remain preserved; official accuracy is unmeasured.

## Preserve the comparison

V4's original candidates, failures, and usage remain unchanged. Its implementation is preserved at commit `1481df68580bb42cde767708e370ca311cc65ea6`; its [baseline review](baseline_v4_review.md) remains the historical reference. Current code can read/export that checkpoint but cannot resume it under a changed implementation fingerprint.

A later course evaluation should use a new name such as `gaia_controller_v5`. The CLI's default name has been updated accordingly. Do not pool results from the four-request fresh pilot with the eight-request course baseline or describe pilot success as a GAIA score. Source-reading fallback, CAPTCHA detection, complete comparisons, model reasoning errors, attachment/video inputs, model-only comparison, public Space/demo, and official grading remain separate work.
