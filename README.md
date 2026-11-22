# TraceAgent

An evidence-backed research agent being built for the Hugging Face Agents Course final project, with a reproducible evaluation and a public demonstration as the end goal.

**Current status: v10 can cite a short exact quote when the citation catalog omits the needed text.** The final response and correction accept either a registered excerpt ID or a verified verbatim quote. All 140 offline tests pass, and a one-request fictional pilot is prepared. The v9 year check passed its one-request pilot and remains active. V4 and v8 each produced eight candidates on the same 20 course tasks. Official scoring and the public Space are pending. See the [v10 design and pilot](docs/quote_fallback_v10.md) and [completed v4/v8 comparison](docs/evidence_v8.md#completed-course-comparison).

## Milestone 1: run a connection test

Use Python 3.11 and [uv](https://docs.astral.sh/uv/). The following commands are for Windows PowerShell, run from the project folder:

```powershell
uv sync --python 3.11
Copy-Item .env.example .env
notepad .env
```

If `.env` already exists, edit it rather than copying over it. Paste an existing Gemini Developer API key after `GEMINI_API_KEY=` and save locally. You do not need a separate key for this project. `.env` is excluded from Git; `.env.example` contains no secret.

Before making a live call, open [AI Studio's API keys page](https://aistudio.google.com/api-keys) and check that the key's Google project uses the **Free tier**. Keep billing disabled. The application cannot verify your billing tier. Environment variables override `.env`; if `GEMINI_API_KEY` and `GOOGLE_API_KEY` both exist and differ, setup stops so you can choose the intended project.

```powershell
# Offline: checks dependencies and configuration without contacting Google.
uv run python -m traceagent check

# Live metadata request: lists models with text-generation support.
uv run python -m traceagent list-models

# Live generation request: asks the configured model to reply READY.
uv run python -m traceagent smoke
```

Success looks like `Reply: READY` followed by `Connection test passed.` Token counts are reported when supplied by Google. This only verifies connectivity and a simple output instruction; it does not measure research or agent performance.

The starting model is `gemini-3.6-flash`, listed with free input/output in [Google's pricing documentation](https://ai.google.dev/gemini-api/docs/pricing) when checked on 2026-11-15. A local live smoke test returned READY in 1.92 seconds, with 11 input tokens and 122 total tokens. This is one successful connectivity observation, not a model quality or speed benchmark. The previous 3.8 Flash attempt returned HTTP 503; it remains available as a configurable model for future investigation. Verify current pricing and your own project quota before use. Listing a model does **not** prove that it has free quota for your account. Requests use the configured model only; there is no fallback to another model, no paid search tool, and each model call uses one SDK attempt. Rate limits produce a short error so you can wait and rerun later.

If the smoke test reports `Google API HTTP 500`, `502`, `503`, or `504`, it received a server/gateway error. The diagnostic shows the numeric status without printing the provider response body. Wait briefly and try the smoke test once more. If it persists, run `list-models` and share the status plus the model list for diagnosis. Successful model listing only establishes metadata access; it does not establish generation access, free quota, or the absence of a model-specific service issue. Do not enable billing to work around a temporary server error. See [Google's troubleshooting guide](https://ai.google.dev/gemini-api/docs/troubleshooting).

## Milestone 2: run the first tool loop

```powershell
uv sync --python 3.11
uv run python -m traceagent agent "What is 17 times 23?"
```

The expected behavior is a `multiply` tool event with a result of `391.0`, followed by a final answer containing 391. The exact wording and number of model calls may vary. Model calls are limited to four and tool calls to six; a run that reaches either limit without an answer reports that it stopped.

The calculator graph has two nodes: `model` and `tools`. Research also includes an answer-review node. A conditional edge routes a model tool request to Python. Python returns the result as a `functionResponse` part in a `user` message and the graph calls the model again. The Gemini endpoint rejected the previous `tool` role; tool output is identified by its part type and matching function-call ID. A model reply without a tool request ends the loop. Google SDK automatic function execution is disabled so LangGraph controls when tools run. Full model message objects are preserved between requests, including Gemini thought signatures; the CLI displays tool names, arguments, results, and the final answer rather than internal model reasoning.

If the agent fails while the smoke test succeeds, use `uv run python -m traceagent agent "What is 17 times 23?" --diagnose`. The diagnostic distinguishes HTTP 400 (request validation), 401 (authentication), and 403 (permissions), reports which model request failed and how many tool calls completed, and shows a short provider message with API keys and common credentials redacted. Raw response bodies and headers are excluded. The tool declaration omits an inferred numeric return schema because function responses are wrapped as `{"result": ...}` or `{"error": ...}` objects.

## How the code fits together

| File | Responsibility |
| --- | --- |
| `traceagent/config.py` | Load the local key and model, detect conflicting keys, hide secrets in settings representations |
| `traceagent/__main__.py` | Implement setup commands and display agent tool events and run metrics |
| `traceagent/agent.py` | Model/tool routing, message history, call limits, and usage accounting |
| `traceagent/tools.py` | Python tools and the registry of functions the model can request |
| `traceagent/web.py` | Public URL checks, bounded source downloads, extraction, and search backends |
| `traceagent/research.py` | Per-run sources, quote checks, research orchestration, and JSON run records |
| `traceagent/evaluation.py` | Fixed snapshots, request reservations, task queues, resume policy, and full-set exports |
| `traceagent/budget.py` | Identify locally blocked requests separately from provider failures |
| `.env.example` | Document local settings without storing credentials |
| `tests/test_setup.py` | Exercise credential handling and the offline/live request boundary |
| `tests/test_agent.py` | Exercise graph routing, call limits, signatures, tool responses, and arithmetic boundaries |
| `tests/test_research.py` | Exercise source reading, search requests, provenance checks, limits, and failure records |
| `tests/test_evaluation.py` | Verify durable request budgets, quota stops, interruption/resume, configuration integrity, and export coverage |

The Google SDK provides the model connection and LangGraph manages the tool loop. Gradio will provide the demonstration interface later.

## Milestone 3: research with sources

```powershell
uv sync --locked --python 3.11
uv run python -m traceagent research "Read https://docs.python.org/3/library/math.html and determine what math.isfinite returns for infinity and for NaN. Give the two boolean results with supporting evidence from that page." --diagnose
```

This source-provided question can be answered by opening its URL. For questions that require source discovery, configure search in the existing local `.env`:

```dotenv
SEARCH_BACKEND=serper
SERPER_API_KEY=your_private_signup_key
```

Keep the existing Gemini settings, and replace any existing `SEARCH_BACKEND` value rather than adding a duplicate. [Serper](https://serper.dev/) currently advertises 2,500 free signup queries without a credit card and stops accepting queries when the balance reaches zero. Use that allowance only, without paid credit purchases or automatic top-ups; do not assume monthly renewals. The adapter makes a standard web search, returns organic URLs/snippets only, and ignores direct answer boxes. Each run caches repeated queries and permits at most four search requests. A full 20-task evaluation would therefore request at most 80 searches with the current limits, excluding separate development runs.

Tavily remains selectable with `SEARCH_BACKEND=tavily` and a local `TAVILY_API_KEY`. Its [Researcher plan](https://docs.tavily.com/documentation/api-credits) lists 1,000 free monthly credits without a credit card; keep pay-as-you-go disabled. That adapter explicitly requests basic search and disables generated answers and automatic search-depth selection. Tavily's signup site returned CloudFront 403 errors for the owner, and a subsequent Serper search-to-answer run succeeded. Neither adapter automatically retries requests or switches providers. The application cannot inspect account billing settings. A no-account option remains available with `SEARCH_BACKEND=ddgs`, but public search endpoints may return challenges or no results. The application does not bypass those challenges.

```powershell
uv run python -m traceagent research "According to the official Python documentation, what does math.isfinite return for infinity and for NaN?" --diagnose
```

The research profile permits eight model calls and twelve tool calls, with a 90-second deadline per model request and bounded web/PDF operations. Other CLI commands retain a 30-second model-request deadline. There are no automatic provider/transport retries. A format or evidence error can trigger one final-answer correction within the existing eight-call budget, using retained observations with tool calls disabled. A second validation failure ends the run. Research output is capped at 4,096 tokens per request. Gemini 3.6 Flash uses low thinking for this profile; other models retain their defaults. These settings need evaluation on harder tasks. The run records per-request finish reasons and reported thinking/output token counts. A `MAX_TOKENS` response produces `output_limit` and is rejected before accepting an answer or executing its tool calls. A final answer requires a short matching quote from an opened source, or from the supplied question (Q1) for self-contained reasoning. Correction and reserved-final requests use a JSON response schema with no tool declarations; earlier tool-selection turns can still produce a final response that is locally checked. Q1 is labeled as question evidence and does not independently establish external facts. This checks provenance and output format, not whether the quote logically proves every claim. Quotes are limited to 25 words per source URL. Unsupported or unverifiable answers are reported explicitly. Correction counts and validation outcomes are recorded separately from tool calls. JSON run records are written under the ignored `runs/` directory and contain sources, actions, configuration, available usage, runtime, and status; they exclude internal model messages and redact configured credentials. A [curated source-reading example](examples/live_source_read.json) omits the full retrieved passages. The [research walkthrough](docs/research_walkthrough.md) records the subsequent owner-run search-to-answer CLI result; its full local JSON was not inspected. The [live PDF research record](examples/live_pdf_research.json) records the later directly inspected search/read/calculate/correct workflow.

PDF support extracts text, with page and time limits; scanned documents need a future OCR capability. The current reader does not execute webpage JavaScript. Direct connections pin validated public IPs; configured proxies are trusted to route validated hostnames and require their own destination controls before public hosting.

## Milestone 4: evaluate within a request budget

The [evaluation walkthrough](docs/evaluation_walkthrough.md) describes saved results and request accounting. The [v10 pilot](docs/quote_fallback_v10.md) uses a supplied fictional inventory and a one-request cap. The owner already has the pilot prepared. On a fresh checkout, prepare it once before running it:

```powershell
uv run python -m examples.prepare_quote_fallback_pilot
uv run python -m traceagent eval run --name quote_fallback_pilot_v10 --request-budget 1 --max-tasks 1 --diagnose
```

Historical checkpoints can be inspected and exported. A live evaluation requires a profile prepared with the same implementation.

Preparation/status/export make no Gemini requests. A run uses its frozen profile and checkpoints a reservation before every SDK HTTP attempt. Task/session request limits, provider-error queue stops, atomic writes, and writer locks preserve progress. Completed tasks survive interruptions. Interrupted tasks restart from their question on explicit resume. SDK automatic function execution, response continuation, and retries are disabled. Each invocation's budget is a new local session allowance, not a provider quota estimate.

The final permitted request has no tools and requests schema-constrained JSON. The one allowed correction uses the same mode within the original cap. Early final responses are locally checked; quotes and source IDs must match. A live correction returned valid JSON but failed evidence verification, showing that formatting does not establish provenance or correct reasoning. Missing-focus notices and per-task status/diagnostic messages expose other failures. Reserved finalization has been observed live, including explicit unresolved output; this does not establish answer accuracy.

Source audits cover search snippets as well as opened pages. V4 excludes course walkthrough context without requiring an answer keyword, task-goal metadata, and sources repeating ten consecutive normalized question words in URLs, titles, snippets, document text, or links. It also excludes Medium, LinkedIn, Reddit, and Wordplays during benchmark runs. Ordinary research is not subject to those exclusions. The policy is conservative: it can reject legitimate sources and miss paraphrased solutions, so further audits and fresh tasks remain necessary.

## Historical evaluation checkpoints

Runtime checkpoints stay under the ignored `evaluations/` folder. V3 is preserved with two generated candidates, one unresolved task, ten pending tasks, and seven unsupported inputs after fourteen request attempts; it is invalidated for scoring and exports withhold its answers. An offline replay excluded five of six retained search observations under the new policy and left the Wikipedia source available. No final answer had been observed in the exposed walkthrough snippets, so this is an independence concern rather than a proven final-label leak. The [v4 preparation summary](examples/evaluation_v4_prepared.json) records the findings without benchmark questions or answers.

V4 starts the same twenty-question snapshot with no previous candidates or observations: thirteen pending tasks, seven unsupported inputs, and zero requests. Its first live task prepared one ungraded answer using six model requests, five tool calls, and 22.994 seconds. Twelve tasks remain pending and seven inputs unsupported. Review found no task-specific walkthrough or answer-key material in the returned search observations. The [v4 session summary](examples/evaluation_v4_session_summary.json) records metrics and review findings without benchmark questions or answers. All six responses were normal turns; the reserved finalizer and correction were not exercised. Four similar searches still preceded the page read. No official score, completed full-set baseline, or accuracy comparison is available.

The second v4 task used two model requests, one evidence correction, and zero tools. Its corrected JSON and Q1 quote passed deterministic checks, but manual review found an unrequested output transformation. The generated candidate is preserved for faithful grading. After that attempt, V4 had two prepared candidates, eleven pending tasks, and seven unsupported inputs after eight request attempts. This is coverage, not a correctness count. The [reasoning review](examples/evaluation_v4_reasoning_review.json) records the distinction without publishing the question or answer; official grading remains unmeasured.

The third v4 task prepared a candidate using seven model requests, six tools, and 17.412 seconds. Returned snippets and opened sources were Wikipedia pages; the primary archive contains the promotion date and quoted nominator attribution. One result was filtered before model exposure. V4 now has three generated candidates, ten pending tasks, and seven unsupported inputs after fifteen request attempts. The earlier reasoning concern remains flagged; these are coverage counts, not measured correct answers. The [research review](examples/evaluation_v4_research_review.json) records source checks and remaining evidence limits without the question or answer.

Review of the next three v4 records found another reasoning error in an earlier operation-table candidate, an unresolved retrieval/version-selection case, and a search loop ending in a fabricated citation. A direct calculation from the supplied table disagrees with its generated answer field; the original candidate is preserved. The source-retrieval case exercised the finalizer and returned unresolved from incomplete excerpts. The latest task used four searches, requested three more after exhaustion, never opened a source, and cited an unopened snippet as S1; the evidence checker rejected it. At that checkpoint, V4 had four prepared candidates (two with manual reasoning flags), two unresolved tasks, seven pending tasks, and seven unsupported inputs after thirty-five request attempts. These remain coverage/review findings, not an official correctness count. The [failure review](examples/evaluation_v4_failure_review.json) omits benchmark questions/answers and records the issues for a later revision; v4 remains frozen while remaining supported tasks are evaluated.

The following multi-hop task prepared a candidate using four requests, three tools, and 9.07 seconds. The opened actor biography supports the final role quote and lists both show roles, while the adaptation-identification link was discovered from an unopened search snippet. No task-specific walkthrough/answer-key material was observed in returned content; one result was filtered before exposure. The [multi-hop review](examples/evaluation_v4_multihop_review.json) records the partial evidence chain without benchmark questions or answers. After that attempt, V4 had five generated candidates, two unresolved tasks, six pending tasks, and seven unsupported inputs after thirty-nine request attempts. Two earlier manual reasoning flags remain, and official grading is unmeasured.

The eighth v4 task encountered HTTP 403 while reading a statistics site, then kept searching without opening available alternative URLs. It finalized unresolved after eight requests, with no successful source read. A returned agent-research snippet also contained a related lookup query; no answer was accepted from this attempt, and the screening limitation is recorded. The [source-access review](examples/evaluation_v4_source_access_review.json) omits the benchmark question and answer. V4 now has five generated candidates, three unresolved tasks, five pending tasks, and seven unsupported inputs after forty-seven request attempts. The implementation remains unchanged and official grading is unmeasured.

The ninth v4 task used eight requests, three searches, and four read calls. Its final quotation came from search snippets and was attributed to the wrong source; it appeared in none of the retained page passages. The publisher returned a CAPTCHA, while the preprint excerpt was incomplete and an identical cached reread added no text. The evidence checker withheld the answer. Returned agent-research snippets also paraphrased the task goal, so no clean solved-result claim is made. The [quote-provenance review](examples/evaluation_v4_quote_provenance_review.json) omits the question and answer. V4 now has five generated candidates, four unresolved tasks, four pending tasks, and seven unsupported inputs after fifty-five request attempts. The original records and fixed implementation remain unchanged; official grading is unmeasured.

The remaining four v4 tasks produced three candidates and one unresolved result. All thirteen supported tasks are now processed: eight candidates, five unresolved tasks, seven unsupported inputs, and zero pending tasks after seventy-nine request reservations. Quote corrections succeeded on two later candidates, but a comparison task retains an unverified tie-break; a historical-roster task confused an unverified search premise with a statistics column. The final candidate has matching competition-table evidence. The [completed summary](examples/evaluation_v4_completed_summary.json) and [baseline review](docs/baseline_v4_review.md) record usage, evidence limits, and proposed controller improvements without benchmark questions or answers. Eight candidates are answer coverage, not a measured score.

## System design and review

The project owner directs requirements, capabilities, architecture tradeoffs, evaluation criteria, and the demonstration experience. Implementation and automated testing are handled with coding assistance. Understanding the system does not require completing coding exercises.

Review the [system design](docs/system_design.md), follow the evidence and decisions in example runs, and assess whether the observed behavior meets the agreed requirements. The calculator tools demonstrate the control loop; web and file research will supply the project's broader capabilities.

The [requirements and capability roadmap](docs/requirements.md) records the benchmark input inventory and the acceptance criteria for research workflows with inspectable source evidence. A simple search/read/answer run has succeeded; a live PDF/calculation task with one citation correction has also succeeded. The saved-queue evaluator now supports broader task evaluation; the replacement baseline has prepared one ungraded answer after the earlier run was invalidated. See the [source-audit summary](examples/evaluation_source_audit.json).

A live multiplication run returned 391 in 3.23 seconds, using two model calls, one tool call, 368 input tokens, and 470 total tokens. This is a single observed run, not a performance benchmark. The combined multiplication/addition scenario is covered by offline graph tests; live validation of addition remains pending.

## Offline checks

```powershell
uv run python -m unittest discover -s tests -v
```

Configuration and arithmetic-boundary tests also run using plain Python 3.11 without third-party dependencies: `python -m unittest discover -s tests -v`. SDK and graph tests are skipped when dependencies are absent; CI installs them and runs those checks too. Automated tests make no live model or search calls. A passing test suite does not establish live provider connectivity. Live checks require a locally configured key.

## Planned evaluation

- Compare the same model with and without access to research tools.
- Report exact-match accuracy on the course's 20-question GAIA validation subset, clearly separated from performance on the full GAIA benchmark.
- Record model configuration, tool activity, sources, runtime, usage, and failures.
- Add fresh tasks beyond the course subset to check generalization.
- Generate answers through the agent; do not hard-code benchmark answers or retrieve published answer lists.

## References

- [Hugging Face final assignment](https://huggingface.co/learn/agents-course/en/unit4/hands-on)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
- [LangGraph quickstart](https://docs.langchain.com/oss/python/langgraph/quickstart)
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
