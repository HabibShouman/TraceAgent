# V6: allow recovery while enforcing budgets

Implemented 2026-11-21. V5 is preserved as a partial diagnostic run, not a completed accuracy baseline. After six supported tasks it retained four candidates, two with identified reasoning errors, and two unresolved results. Seven supported tasks remain pending and seven inputs unsupported. The original candidates, reasons, and 25 request reservations are unchanged.

## Why change the rule?

In the last two v5 tasks, search was paused after URLs were returned, but the model never selected the still-available reader. It attempted two more searches and then returned unresolved with numerical allowance remaining. One result set was mostly irrelevant or query-shaped; the other included useful botany sources and a university PDF. The model's access/allowance explanations were not supported by actual read failures.

The mandatory pause did not reliably produce reading. It also prevented refinement when a result set was unsuitable. URL presence alone was too weak a basis for taking search away. The [partial diagnostic review](../examples/evaluation_v5_partial_review.json) records these failures without publishing questions or answers. The first six v4/v5 tasks have the same accepted-answer coverage; no accuracy gain was established. V4 also had provider failures, so raw request totals are not a controlled causal comparison.

## Current rules

| Situation | V6 behavior |
| --- | --- |
| Search results arrive | Keep search available while its allowance remains; recommend opening relevant sources |
| Results are irrelevant or a specific fact is missing | Permit a refined query without forcing a read first |
| Four actual searches have been requested | Remove search from subsequent declarations and deny execution of any additional search |
| A model requests an unavailable tool | Return the reason and a list of tools available for its next request |
| Search is exhausted | Reading an existing public URL and arithmetic remain available |
| Final permitted request or answer correction | No tools; answer from retained evidence or report unresolved |

Hard caps and per-call execution checks remain in place, including inside a batch of model-selected calls. Search snippets still cannot serve as opened-source evidence. Cached queries refresh their displayed remaining allowance without mutating earlier observations. A new explicit instruction distinguishes unavailable search from a website-access failure; it does not guarantee that the model will report the cause correctly.

This revision removes a planning constraint, not a resource guard. The same Gemini model, standard eight-model-request/twelve-tool/four-search limits, source filter, quotation checks, and one-answer-correction limit remain. No extra model, automatic retry, paid fallback, or budget increase was added.

## Verification and pilot

121 offline tests pass locally. The availability suite has eleven cases, including a fabricated recovery from an irrelevant first result to a refined query, relevant read, and supported answer within four scripted model requests. Tests also check a five-search batch executing at most four provider requests, denial reasons that retain the reader as an option, stale cache-budget metadata, invalid URLs, failed reads, preserved protocol state, and explicit unresolved output. The historical v5 preparation helper refuses to create a new profile under the old name with changed code.

Mocked responses verify control behavior; they do not establish live planning quality or an accuracy improvement. Two known reasoning errors, long source context, query-shaped results, missing attachment/video readers, official scoring, and the public demo remain separate work.

A fresh question about the return types of Python's `math.frexp` is prepared outside GAIA with a four-request cap. Preparation uses no credentials or API calls:

```powershell
uv run python -m examples.prepare_controller_pilot_v6
```

The owner's working project already has it prepared. Run it once:

```powershell
uv run python -m traceagent eval run --name controller_pilot_v6 --request-budget 4 --max-tasks 1 --diagnose
```

The [preparation summary](../examples/controller_v6_prepared_summary.json) records zero live attempts and the new implementation fingerprint. Review the returned sources, answer, and actions before preparing another course run. V4/v5 checkpoints remain readable/exportable, but changed code cannot resume their frozen implementations. V5's source is preserved at commit `7e9b172bf5428a4627acb4d3957cfc688d633305`. The default name for a later course profile is `gaia_controller_v6`; no new full course run has been started.
