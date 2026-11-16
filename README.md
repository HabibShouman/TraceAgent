# TraceAgent

An evidence-backed research agent being built for the Hugging Face Agents Course final project, with a reproducible evaluation and a public demonstration as the end goal.

**Current status: milestone 3 - source reading, research tools, and evidence records.** A live source-reading task completed with a cited answer and checked source passages. HTML/text/PDF reading, bounded arithmetic/research tools, session caching, and saved run records are implemented. A user-reported live Serper run searched for and opened Python's official documentation, then returned an answer supported by the displayed passage. Tavily is implemented but not live-validated; the no-account DDGS option encountered challenges in the development environment. This single straightforward example establishes integration, not general research accuracy. The interface and benchmark runner remain planned, and no benchmark score has been measured. See the [research walkthrough](docs/research_walkthrough.md).

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

The graph has two nodes: `model` and `tools`. A conditional edge routes a model tool request to Python. Python returns the result as a `functionResponse` part in a `user` message and the graph calls the model again. The Gemini endpoint rejected the previous `tool` role; tool output is identified by its part type and matching function-call ID. A model reply without a tool request ends the loop. Google SDK automatic function execution is disabled so LangGraph controls when tools run. Full model message objects are preserved between requests, including Gemini thought signatures; the CLI displays tool names, arguments, results, and the final answer rather than internal model reasoning.

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
| `.env.example` | Document local settings without storing credentials |
| `tests/test_setup.py` | Exercise credential handling and the offline/live request boundary |
| `tests/test_agent.py` | Exercise graph routing, call limits, signatures, tool responses, and arithmetic boundaries |
| `tests/test_research.py` | Exercise source reading, search requests, provenance checks, limits, and failure records |

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

The research profile permits eight model calls and twelve tool calls, with bounded web/PDF operations. A final answer requires a source ID from an opened page/document and a short quote found in the retained source passages. This checks provenance and output format, not whether the quote logically proves every claim. Quotes are limited to 25 words per source URL. Unsupported or unverifiable answers are reported explicitly. JSON run records are written under the ignored `runs/` directory and contain sources, actions, configuration, available usage, runtime, and status; they exclude internal model messages and redact configured credentials. A [curated source-reading example](examples/live_source_read.json) omits the full retrieved passages. A [search-to-answer summary](examples/live_search_summary.json) records the subsequent owner-run CLI result; its full local JSON was not inspected.

PDF support extracts text, with page and time limits; scanned documents need a future OCR capability. The current reader does not execute webpage JavaScript. Direct connections pin validated public IPs; configured proxies are trusted to route validated hostnames and require their own destination controls before public hosting.

## System design and review

The project owner directs requirements, capabilities, architecture tradeoffs, evaluation criteria, and the demonstration experience. Implementation and automated testing are handled with coding assistance. Understanding the system does not require completing coding exercises.

Review the [system design](docs/system_design.md), follow the evidence and decisions in example runs, and assess whether the observed behavior meets the agreed requirements. The calculator tools demonstrate the control loop; web and file research will supply the project's broader capabilities.

The [requirements and capability roadmap](docs/requirements.md) records the benchmark input inventory and the acceptance criteria for research workflows with inspectable source evidence. A simple search/read/answer run has succeeded; a live PDF task and broader evaluation remain next.

A live multiplication run returned 391 in 3.23 seconds, using two model calls, one tool call, 368 input tokens, and 470 total tokens. This is a single observed run, not a performance benchmark. The combined multiplication/addition scenario is covered by offline graph tests; live validation of addition remains pending.

## Offline checks

```powershell
uv run python -m unittest discover -s tests -v
```

Configuration and arithmetic-boundary tests also run using plain Python 3.11 without third-party dependencies: `python -m unittest discover -s tests -v`. SDK and graph tests are skipped when dependencies are absent; CI installs them and runs those checks too. All tests use mocks and consume no model quota. A passing test suite does not establish live provider connectivity. Live checks require a locally configured key.

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
