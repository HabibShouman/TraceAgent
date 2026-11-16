# First research workflow

Updated 2026-11-16. Review this at the level of system behavior and evidence.

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

## Next controlled check: PDF evidence and calculation

Run a non-benchmark question that requires opening the original paper PDF and using a calculation tool. The test prompt deliberately requests these actions to verify the capabilities; it does not measure whether the agent would choose them without guidance.

```powershell
uv run python -m traceagent research "Find and open the PDF of Attention Is All You Need. For the base Transformer, identify the number of encoder layers and the number of attention heads per encoder self-attention layer. Use the multiply tool to calculate their product. Support both inputs with short quotes and PDF page numbers." --diagnose
```

Review whether the trace includes search, a successful PDF read with page locations, a multiplication call using the retrieved inputs, and an answer supported by the cited passages. Runtime, failed reads, and any incorrect evidence should remain visible. A passing result would validate this composed capability path, not establish general PDF accuracy.

## First PDF attempt: provider deadline failure

The owner supplied a subsequent run that searched for the paper but stopped on model request 2 with HTTP 504 and a redacted "Deadline expired before operation could complete" message. No PDF read or calculation occurred. The completed work used one model call and one search tool call; the CLI reported 742 input tokens, 926 total tokens, and 36.41 seconds. These token counts cover reported completed requests, not any unreported processing by the timed-out request. The run retained a provider-error outcome and produced no answer.

At that point the client set a 30-second deadline for every request. [Google's error guidance](https://aistudio.google.com/docs/api-errors) recommends increasing the client deadline for HTTP 504. Research calls now allow 90 seconds per request; the other CLI commands keep 30 seconds. Each request still has one SDK attempt, with the same model/tool/search budgets and no automatic provider fallback. This change may help a slow response finish; it does not establish that the client deadline was the sole cause or guarantee recovery. A live rerun is pending.

## What to review together

1. Does the agent choose a relevant, authoritative source?
2. Does it open the source and retrieve the actual supporting material?
3. Does the cited passage justify the answer, beyond merely matching the source text?
4. Does the trace show sensible actions and an appropriate stopping point?
5. If a source is inaccessible or the budget is exhausted, does the system report the failure clearly?

## Scope and limitations

Research runs are bounded at eight model calls, twelve tool calls, and four searches, with a 90-second deadline per model request. Downloads are limited to 8 MiB. PDF extraction runs in a time-limited child process and reads at most 40 pages with bounded retained text; it does not supply OCR or a production memory sandbox. Source truncation and page coverage are reported.

Direct web connections use public-address validation and IP pinning with TLS hostname verification. Configured proxies use validated hostnames and are trusted for routing and destination policy. Production egress and resource controls remain necessary before exposing arbitrary-source reading publicly.

Attachment routing, audio/image/video handling, the Gradio interface, and the full benchmark runner remain later milestones. This workflow has not been scored on GAIA.
