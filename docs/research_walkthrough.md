# First research workflow

Updated 2026-11-17. Review this at the level of system behavior and evidence.

## What is working

The controller can call arithmetic tools, search for sources through a configured backend, and read HTML, text, or text-based PDF sources. Each successful read creates a source ID with retained passages and locations. The final response separates the answer from its evidence, and a local checker tests source-ID and quote membership. A JSON record preserves actions, status, configuration, usage, and sources.

The checker does not independently establish factual entailment. A person still needs to assess whether the supporting passage justifies the answer and whether the source is appropriate.

## Observed live example

The question supplied the URL of Python's official math documentation and asked about finite-number checks for two special floating-point values. The controller opened that page, read relevant passages, and produced an answer with supporting evidence. Because the source URL was supplied, search was not needed.

| Observation | Result |
| --- | --- |
| Outcome | Answered, with source/quote membership check passed |
| Model | Gemini 3.6 Flash |
| Model calls | 2 |
| Tool calls | 1 source read |
| Reported input tokens | 5,609 |
| Reported total tokens | 6,485 |
| Elapsed time | 30.073 seconds |

These are measurements from one run, not a benchmark or speed comparison. The [curated run record](../examples/live_source_read.json) contains the answer, supporting quote, source URL, action, and configuration. Full source passages and internal model messages are omitted from the public example.

## Search-to-answer run reported by the owner

The owner supplied terminal output from a live run on 2026-11-16. The question required web search and an official source, without supplying a URL. The trace shows a search for `site:docs.python.org math.isfinite`, a read of Python's math documentation as S1, and an answer that the function returns False for both infinity and NaN. The displayed excerpt directly supports both results.

| Observation | Result |
| --- | --- |
| Search provider | Serper, as shown by the preceding configuration check |
| Outcome | Answered, with source-ID and quote membership reported as passed |
| Model | Gemini 3.6 Flash |
| Model calls | 3 |
| Tool calls | 2: one search, one source read |
| Reported input tokens | 7,406 |
| Reported total tokens | 8,470 |
| Elapsed time | 66.62 seconds |

The [curated summary](../examples/live_search_summary.json) transcribes the owner-provided CLI output. The full local JSON record was not inspected, and tool-level timing is unavailable here. The model's initial action selected search; after the search result it opened the source; after the read it produced the supported answer. This establishes one complete integration path. It does not establish broad accuracy, benchmark performance, or stable latency. The roughly one-minute runtime remains an observation to investigate before a public demo.

## Why the search connection is separate

Source discovery and source reading have different responsibilities. Search returns candidate URLs and snippets; the reader obtains citable material. Search snippets alone cannot pass the evidence check.

The no-account DuckDuckGo/Bing path returned challenges or no results in this environment. A live research attempt exhausted its budget without claiming a supported answer, and saved the failed actions. The page reader then needed proxy-compatible hostname routing. After that change, the URL-supplied run succeeded.

Tavily's signup website returned a CloudFront 403 error for the owner on both computer and phone. That message alone does not establish the cause. Serper is now implemented as another explicitly selectable provider; source reading, evidence checks, and the controller do not depend on the provider.

Serper's configured search path has now completed the simple question above. [Serper's free signup allowance](https://serper.dev/) remains the selected source-discovery option. Its site advertises 2,500 queries without a credit card, and queries stop when the balance reaches zero. Treat this as a signup allocation rather than a recurring monthly allowance. Do not purchase credits or enable automatic top-ups. With four searches per run, one full 20-question evaluation would request at most 80 searches; separate experiments also consume the balance.

The adapter is tested using mocked responses for request format, organic result parsing, caching, auth/quota failures, and credential redaction. The owner has now supplied output from a successful live Serper run. Direct answer boxes are discarded; the agent must open sources to obtain citable evidence. Tavily remains optional, using basic search with generated answers and automatic depth selection disabled. There are no automatic request retries or provider switches, and the application does not verify account billing settings.

## Reproduce the PDF evidence and calculation check

Run a non-benchmark question that requires opening the original paper PDF and using a calculation tool. The test prompt deliberately requests these actions to verify the capabilities; it does not measure whether the agent would choose them without guidance.

```powershell
$env:GEMINI_MODEL = "gemini-3.5-flash-lite"
uv run python -m traceagent research "Find and open the PDF of Attention Is All You Need. For the base Transformer, identify the number of encoder layers and the number of attention heads per encoder self-attention layer. Use the multiply tool to calculate their product. Support both inputs with short quotes and PDF page numbers." --diagnose
```

Review whether the trace includes search, a successful PDF read with page locations, a multiplication call using the retrieved inputs, and an answer supported by the cited passages. Runtime, failed reads, and any incorrect evidence should remain visible. The successful run below validates this composed capability path on one question; it does not establish general PDF accuracy.

## First PDF attempt: provider deadline failure

The owner supplied a subsequent run that searched for the paper but stopped on model request 2 with HTTP 504 and a redacted "Deadline expired before operation could complete" message. No PDF read or calculation occurred. The completed work used one model call and one search tool call; the CLI reported 742 input tokens, 926 total tokens, and 36.41 seconds. These token counts cover reported completed requests, not any unreported processing by the timed-out request. The run retained a provider-error outcome and produced no answer.

At that point the client set a 30-second deadline for every request. [Google's error guidance](https://aistudio.google.com/docs/api-errors) recommends increasing the client deadline for HTTP 504. Research calls now allow 90 seconds per request; the other CLI commands keep 30 seconds. Each request still has one SDK attempt, with the same model/tool/search budgets and no automatic provider fallback. This change may help a slow response finish; it does not establish that the client deadline was the sole cause or guarantee recovery. A later rerun is described below.

## Follow-up PDF attempt: incomplete final output

The owner's next run searched, read the paper PDF twice, and completed a multiplication tool call. It used five model calls and four tool calls, with 20,421 input tokens, 22,989 total tokens, and 70.32 seconds. Final validation reported a format error. Inspecting the saved candidate showed that it ended in the middle of the evidence array. PDF retrieval and tool execution were observed, but a complete evidence-checked answer was not produced.

The prior run did not capture finish reasons, so token-limit truncation is likely rather than confirmed. [Google documents](https://aistudio.google.com/docs/thinking#token-limits) that the output cap includes thinking tokens. The research profile now uses a 4,096-token cap and low thinking for Gemini 3.6 Flash. Other models retain their default thinking setting. This is a quality/latency tradeoff to evaluate, not a guaranteed improvement.

That revision recorded finish reasons and available token counts per response, preserved incomplete final text separately from an accepted answer, and stopped on `MAX_TOKENS` with `output_limit`. It also rejected non-success finish reasons before executing tool calls. It did not attempt a final-answer correction. The later model comparison and bounded correction are described below.

## Next rerun: daily quota exhausted

After installing the output/thinking revision, the owner reported one completed model request and a search, followed by HTTP 429 on model request 2. The provider explicitly named a 20-request free daily allowance for this project/model, with a retry interval of roughly ten hours. The run reported 771 input tokens, 881 total tokens, and 17.45 seconds, and saved a provider-error record. It did not reach a PDF read or test the new final-response controls.

No further live generation is needed before quota resets. The [request-budget requirements](requirements.md#free-tier-request-budget) describe the planned batch evaluator's pause/resume policy. At that revision, the implementation preserved individual failed-run actions but did not resume an evaluation queue. Queue support is now described in the [evaluation walkthrough](evaluation_walkthrough.md). At that point, 61 offline tests passed for the output/thinking revision, while a successful live PDF answer remained pending.

## Live PDF result and bounded citation correction

After Gemini 3.6 Flash returned a high-demand HTTP 503, the owner explicitly selected Gemini 3.5 Flash-Lite. Its first run searched, opened the PDF, and calculated 6 times 8 as 48. Direct inspection of the saved source passages confirmed the quoted inputs on pages 3 and 5, but the two quotes totaled 26 words, exceeding the 25-word budget for one URL. The original run correctly remained an evidence error.

The controller now passes final candidates through the validator before ending. A format/evidence error can receive one precise correction request using the existing question, tool observations, and source passages. Tool calling is disabled for that request, and the application also rejects any attempted new tool call during correction. The correction uses the same eight-call model budget; provider errors, output truncation, a second invalid answer, or an exhausted budget stop the run. The provenance and quote-length checks remain unchanged.

A new live run on 2026-11-17 reproduced the complete path. Its first candidate contained 27 quoted words. One correction shortened the evidence to 19 words total. The final quotes support six encoder layers and eight heads per layer, match PDF pages 3 and 5, and the multiply action returned 48. The [curated live record](../examples/live_pdf_research.json) includes the accepted evidence, actions, validation outcomes, and model-response metadata, omitting full source passages and internal model messages.

| Observation | Result |
| --- | --- |
| Outcome | Answered after one citation correction |
| Model / search | Gemini 3.5 Flash-Lite / Serper |
| Model calls | 5, including the correction |
| Tool calls | 3: search, PDF read, multiply |
| Final supporting quotes | 19 words total from the PDF |
| Reported input / total tokens | 13,625 / 14,030 |
| Elapsed time | 81.87 seconds |
| Automated checks | 66 local tests passed; remote CI is checked when publishing |

Manual review confirmed that the quoted inputs support the reported product. Automated quote membership alone does not establish factual entailment. This is one non-benchmark question with explicitly requested tool actions, not a GAIA result or a general speed/quality comparison. Evaluation on broader tasks remains pending.

## What to review together

1. Does the agent choose a relevant, authoritative source?
2. Does it open the source and retrieve the actual supporting material?
3. Does the cited passage justify the answer, beyond merely matching the source text?
4. Does the trace show sensible actions and an appropriate stopping point?
5. If a source is inaccessible or the budget is exhausted, does the system report the failure clearly?

## Scope and limitations

Research runs are bounded at eight model calls, twelve tool calls, and four searches, with a 90-second deadline per model request. Downloads are limited to 8 MiB. PDF extraction runs in a time-limited child process and reads at most 40 pages with bounded retained text; it does not supply OCR or a production memory sandbox. Source truncation and page coverage are reported.

Direct web connections use public-address validation and IP pinning with TLS hostname verification. Configured proxies use validated hostnames and are trusted for routing and destination policy. Production egress and resource controls remain necessary before exposing arbitrary-source reading publicly.

The research-profile evaluator now supports a frozen queue, HTTP request budgets, task-level resume, and full-set draft exports. A source audit invalidated its first evaluation after the second task retrieved a benchmark answer table. The replacement policy permits Q1 supplied-question evidence for self-contained reasoning and filters recognizable solution material in benchmark mode. The replacement evaluation has completed one live task with Wikipedia evidence and eight model requests; it remains ungraded. That task did not exercise a live filter block or Q1 reasoning. The official score remains unmeasured. See the [evaluation walkthrough](evaluation_walkthrough.md). Attachment routing, audio/image/video handling, model-only comparison, and the Gradio interface remain later milestones.

## Reserved finish and structured correction

Partial v2 testing exposed two completed responses with invalid JSON, an unrequested output transformation, and a later task that reached its model-call cap while still selecting tools. A transport failure was separately retained and retried. These outcomes remain recorded; v2 was paused incomplete rather than presented as a full baseline.

The revised controller reserves its final allowed request for a schema-constrained response with tools removed. The one permitted correction uses the same structured mode and cannot extend the request cap. It can report unresolved if the retained evidence is insufficient. Earlier turns may still finish without tools and are locally checked. Source membership, quoted-text limits, and truncation checks remain in force. The prompt guides source opening and requested output formatting; those changes need live evaluation. Missing focus terms produce an explicit excerpt notice, and provider error types/per-task results are visible without raw exception data. V3 is prepared but not live-tested; no official score is available.
