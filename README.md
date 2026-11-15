# TraceAgent

An evidence-backed research agent being built for the Hugging Face Agents Course final project, with a reproducible evaluation and a public demonstration as the end goal.

**Current status: milestone 1 — configuration and Gemini connectivity.** This version checks setup, lists models, and makes an optional single generation call. The agent loop, research tools, user interface, and benchmark evaluation will arrive in later milestones. No benchmark score has been measured.

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

The starting model is `gemini-3.8-flash`, listed with free input/output in [Google's pricing documentation](https://ai.google.dev/gemini-api/docs/pricing) when checked on 2026-11-15. Verify current pricing and your own project quota before use. Listing a model does **not** prove that it has free quota for your account. Requests use the configured model only; there is no fallback to another model, no paid search tool, and the smoke test uses one SDK attempt. Rate limits produce a short error so you can wait and rerun later.

If the smoke test reports `Google API HTTP 500`, `502`, `503`, or `504`, it received a server/gateway error. The diagnostic shows the numeric status without printing the provider response body. Wait briefly and try the smoke test once more. If it persists, run `list-models` and share the status plus the model list for diagnosis. Successful model listing only establishes metadata access; it does not establish generation access, free quota, or the absence of a model-specific service issue. Do not enable billing to work around a temporary server error. See [Google's troubleshooting guide](https://ai.google.dev/gemini-api/docs/troubleshooting).

## How the code fits together

| File | Responsibility |
| --- | --- |
| `traceagent/config.py` | Load the local key and model, detect conflicting keys, hide secrets in settings representations |
| `traceagent/__main__.py` | Implement `check`, `list-models`, and the one-call `smoke` test |
| `.env.example` | Document local settings without storing credentials |
| `tests/test_setup.py` | Exercise credential handling and the offline/live request boundary |

The Google SDK is used directly in this first milestone so the model connection is easy to inspect. LangGraph will manage the tool loop in milestone 2; Gradio will provide the demonstration interface later.

## Shared learning task

1. Configure `.env` and run the three commands above.
2. In `config.py`, find where environment variables take precedence over the file.
3. In `__main__.py`, identify the line that actually requests model generation.
4. Explain why `check` passing does not prove that the API key is valid.

For the next milestone, the learner will implement a small calculator tool with guidance, then inspect when the model chooses to call it.

## Offline checks

```powershell
uv run python -m unittest discover -s tests -v
```

The configuration tests also run using plain Python 3.11 without third-party dependencies: `python -m unittest discover -s tests -v`. SDK request-configuration tests are skipped when dependencies are absent; CI installs them and runs those checks too. All tests use mocks and consume no model quota. A passing test suite does not establish live provider connectivity. Live checks require a locally configured key.

## Planned evaluation

- Compare the same model with and without access to research tools.
- Report exact-match accuracy on the course's 20-question GAIA validation subset, clearly separated from performance on the full GAIA benchmark.
- Record model configuration, tool activity, sources, runtime, usage, and failures.
- Add fresh tasks beyond the course subset to check generalization.
- Generate answers through the agent; do not hard-code benchmark answers or retrieve published answer lists.

## References

- [Hugging Face final assignment](https://huggingface.co/learn/agents-course/en/unit4/hands-on)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
- [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
