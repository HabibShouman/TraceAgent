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

## Why the search connection is separate

Source discovery and source reading have different responsibilities. Search returns candidate URLs and snippets; the reader obtains citable material. Search snippets alone cannot pass the evidence check.

The no-account DuckDuckGo/Bing path returned challenges or no results in this environment. A live research attempt exhausted its budget without claiming a supported answer, and saved the failed actions. The page reader then needed proxy-compatible hostname routing. After that change, the URL-supplied run succeeded.

Tavily's signup website returned a CloudFront 403 error for the owner on both computer and phone. That message alone does not establish the cause. Serper is now implemented as another explicitly selectable provider; source reading, evidence checks, and the controller do not depend on the provider.

The next step is to configure [Serper's free signup allowance](https://serper.dev/) and test a question without a supplied URL. Its site advertises 2,500 queries without a credit card, and queries stop when the balance reaches zero. Treat this as a signup allocation rather than a recurring monthly allowance. Do not purchase credits or enable automatic top-ups. With four searches per run, one full 20-question evaluation would request at most 80 searches; separate experiments also consume the balance.

The adapter is tested using mocked responses for request format, organic result parsing, caching, auth/quota failures, and credential redaction. A live Serper call still requires the owner's key. Direct answer boxes are discarded; the agent must open sources to obtain citable evidence. Tavily remains optional, using basic search with generated answers and automatic depth selection disabled. There are no automatic request retries or provider switches, and the application does not verify account billing settings.

## What to review together

1. Does the agent choose a relevant, authoritative source?
2. Does it open the source and retrieve the actual supporting material?
3. Does the cited passage justify the answer, beyond merely matching the source text?
4. Does the trace show sensible actions and an appropriate stopping point?
5. If a source is inaccessible or the budget is exhausted, does the system report the failure clearly?

## Scope and limitations

Research runs are bounded at eight model calls, twelve tool calls, and four searches. Downloads are limited to 8 MiB. PDF extraction runs in a time-limited child process and reads at most 40 pages with bounded retained text; it does not supply OCR or a production memory sandbox. Source truncation and page coverage are reported.

Direct web connections use public-address validation and IP pinning with TLS hostname verification. Configured proxies use validated hostnames and are trusted for routing and destination policy. Production egress and resource controls remain necessary before exposing arbitrary-source reading publicly.

Attachment routing, audio/image/video handling, the Gradio interface, and the full benchmark runner remain later milestones. This workflow has not been scored on GAIA.
