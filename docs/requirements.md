# TraceAgent: requirements and next milestone

Design baseline, updated 2026-11-17. Research tools and source records are now implemented; observed and pending live checks are separated in the [research walkthrough](research_walkthrough.md). The bounded research-profile evaluation runner is implemented; complete official grading and model-only comparison remain pending.

## Product purpose

A research assistant that answers factual questions using web and file evidence, lets a person inspect its actions and sources, and can be evaluated reproducibly. The same controller will serve interactive use and the course benchmark, with distinct output formatting.

The owner leads requirements and architecture decisions and reviews observed behavior. Coding assistance implements and tests the agreed system. Work stays within free service tiers.

## Benchmark input inventory

The public question endpoint was inspected on 2026-11-16. The following categories describe the delivered input form, not the full set of skills each task requires.

| Primary delivered input | Tasks |
| --- | ---: |
| Question text without an attachment or video link | 13 |
| Attached image | 1 |
| Attached audio | 2 |
| Attached Python file | 1 |
| Attached Excel file | 1 |
| YouTube video link | 2 |
| Total | 20 |

Source: [live question endpoint](https://agents-course-unit4-scoring.hf.space/questions). Questions and ground-truth answers are not embedded in application logic. Text-delivered questions can still require web research and document retrieval. Unsupported input types must remain visible in full-set evaluation results.

## Inputs and outputs

| Area | Required behavior |
| --- | --- |
| Input | Accept a question, required response format, and optional file/reference |
| Interactive answer | Provide the answer, supporting sources/file locations, and a concise explanation |
| Benchmark answer | Supply the requested answer string alone in the submission field |
| Evidence | Associate used facts with source identifiers, retrieved text or file locations, and tool calls |
| Run record | Save configuration, actions, answer/status, runtime, available token counts, and errors |
| Unresolved task | Report the reason for stopping; do not silently replace unsupported tasks with fabricated answers |

## Capability roadmap

| Stage | Capability | Evidence needed to move on |
| --- | --- | --- |
| Working core | Model connection, multiplication, addition, bounded tool loop | Live multiplication observed; dependent arithmetic covered by offline tests |
| Current: web research | Free search adapters, webpage/PDF reading, source records | Live URL-supplied answer observed; owner-reported Serper search/read/answer succeeded; live PDF/calculation with one citation correction also succeeded; broader validation remains |
| File handling | Route and read spreadsheets, images, audio, and code text | Validate each supported input type on independently checked examples |
| Current: baseline evaluation | Frozen 20-task snapshot, request budgets, task-level resume, full-set exports | V1 and v3 invalidated after source audits; partial v2 preserved; validate v4 source policy and complete official grading |
| Targeted improvements | Address failure categories, including video access when justified | Compare new runs against the recorded baseline and report remaining limits |
| Portfolio demo | Usable interface, architecture explanation, result table, selected traces | A reviewer can understand and reproduce at least one complete research workflow |

Image/audio routing and code execution strategy need design and validation. Reading a Python file does not imply permission to execute arbitrary code. Video questions remain in scope for failure analysis even before video support exists.

## Immediate research milestone

Implement a small complete workflow: the agent receives a fresh factual question, searches for relevant material, opens a source, follows a relevant document link when needed, extracts the supporting detail, and returns an answer with its evidence. Use a non-benchmark example for this development demonstration.

Acceptance criteria:

1. At least one relevant source is opened and read; search snippets alone do not establish completion.
2. The cited URL or document location can be traced to a tool result and a supporting passage.
3. The agent's decisions depend on retrieved observations; the application contains no canned answer for the question.
4. A run record retains tool successes and failures, available usage, runtime, and the final status.
5. Missing evidence, inaccessible pages, provider failures, and exhausted budgets produce clear outcomes.
6. The output formatter can keep citations and explanations outside a benchmark answer field.
7. The run uses free services with bounded requests and no paid fallback.

A simple web search/read/answer run has now been observed through owner-provided terminal output. A live PDF/calculation task has also succeeded with one bounded citation correction, as recorded in the walkthrough. The quota-aware evaluation runner is now implemented. Complete baseline grading, input readers, and the demonstration interface remain ahead. This demonstration is not a GAIA score.

The owner will review the question, sources, actions, answer quality, and failure behavior rather than write implementation functions. This review determines whether the workflow is useful and the design needs adjustment.

## Free-tier request budget

A live error on 2026-11-16 UTC reported a daily allowance of 20 generation requests for the owner's current Gemini 3.6 Flash project/model. This is an observed account limit, not a universal model quota. The following PDF rerun completed its first model request and search, then received HTTP 429 on model request 2; at that point the output/thinking revision had not completed a live PDF test. A later Gemini 3.5 Flash-Lite run succeeded, as documented in the walkthrough.

[Google's rate-limit documentation](https://aistudio.google.com/docs/rate-limits) states that limits apply per project, not per API key, and daily request quotas reset at midnight Pacific time. Other activity in the same project can consume the allowance. The reported retry interval pointed to approximately 10:00 on 2026-11-17 in Beirut; the owner should check the active quota dashboard before restarting generation.

The budget counts model requests rather than questions. The successful basic research example used three model calls, and the earlier PDF attempt used five. Benchmark evaluation must therefore support batches across quota resets rather than assume that all 20 tasks fit into one free day.

Implemented evaluation-runner requirements:

1. Accept a bounded request budget for each session; count attempted generation requests conservatively, including failures.
2. Save completed per-task results, configuration, and usage, and skip already completed tasks when continuing the same evaluation.
3. Stop the entire queue on HTTP 429 and preserve unfinished work for an explicit later resume.
4. Distinguish provider/quota errors from wrong answers; retain every task in the complete 20-task report.
5. Do not infer global remaining quota from local logs, because other applications may use the same project.
6. Keep billing disabled and avoid automatic model changes or request retries to work around a quota stop.

These behaviors are implemented in the [evaluation runner](evaluation_walkthrough.md). It preserves task-level results and attempts, enforces session/per-task HTTP request budgets, and restarts interrupted questions from the beginning. It does not yet restore a conversation from its last tool result. The second live task exposed an answer-bearing benchmark source; v1 is invalidated and its original records remain preserved. Version 2 starts fresh with source filters and supplied-question evidence. The official score remains unmeasured. Automated tests make no live generation/search calls.

## Evaluation and public presentation

Keep a model-only comparison and a tool-enabled configuration, with documented inputs and limits. Count failed and unsupported tasks in the complete 20-task report. Record model/tool versions, budgets, and run dates, and use additional independently checked questions beyond the course subset.

The course's exact-match submission requirements and public code-link requirement are described in the [official hands-on instructions](https://huggingface.co/learn/agents-course/en/unit4/hands-on). Public claims must identify the course's 20-question GAIA validation subset rather than imply full GAIA performance.

Portfolio completion means a functioning research workflow, a usable demonstration, an honest evaluation report, and a clear explanation of design choices and limitations. Describe the owner's system-design and evaluation contribution accurately, with coding assistance acknowledged where appropriate.

## Current controller revision

The incomplete v2 baseline is preserved after twenty request attempts across three supported tasks. It exposed repeated search, missing finalization capacity, JSON escaping, reasoning, and transport failures. V3 reserves the last existing request for a tool-free JSON-schema response and uses the same mode for one correction. It adds clearer unmatched-focus notices and terminal diagnostics. V3 uses the same question-only snapshot with no old answers/observations. Its first ordinary research task prepared one ungraded answer using five requests. Structured correction has now returned valid JSON in a second task, but its changed evidence punctuation failed the quote check and its response repeated an unrequested output transformation. Reserved finalization, broader performance, and exact-match accuracy remain unmeasured. See the [evaluation walkthrough](evaluation_walkthrough.md) for the full policy and failure evidence.

## Current source-policy revision

V3 was conservatively excluded from scoring after task-specific walkthrough snippets reached the model through search results. The final opened page was Wikipedia, and no final answer was observed in those snippets; independence is uncertain. All original records remain. V4 adds course-context and copied-question screening plus benchmark-only discussion/answer-site exclusions. The same twenty-question snapshot starts fresh with no old answers or observations. Its live behavior, reserved finalization, and exact-match accuracy remain unmeasured. Broader source exclusion can reduce coverage, and heuristics still require audits. See the [evaluation walkthrough](evaluation_walkthrough.md).
