# TraceAgent

An evidence-backed research agent being built for the Hugging Face Agents Course final project, with a reproducible evaluation and a public demonstration as the end goal.

**Current status: milestone 2 — a bounded LangGraph tool loop.** A live multiplication run completed successfully with Gemini 3.6 Flash. Multiplication and addition are implemented; their dependent use is tested with scripted model responses. Research tools, the user interface, and benchmark evaluation are later milestones. No benchmark score has been measured. See the [system design](docs/system_design.md) for the proposed full architecture.

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
| `.env.example` | Document local settings without storing credentials |
| `tests/test_setup.py` | Exercise credential handling and the offline/live request boundary |
| `tests/test_agent.py` | Exercise graph routing, call limits, signatures, tool responses, and arithmetic boundaries |

The Google SDK provides the model connection and LangGraph manages the tool loop. Gradio will provide the demonstration interface later.

## System design and review

The project owner directs requirements, capabilities, architecture tradeoffs, evaluation criteria, and the demonstration experience. Implementation and automated testing are handled with coding assistance. Understanding the system does not require completing coding exercises.

Review the [system design](docs/system_design.md), follow the evidence and decisions in example runs, and assess whether the observed behavior meets the agreed requirements. The calculator tools demonstrate the control loop; web and file research will supply the project's broader capabilities.

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
