"""Small setup commands. Importing this module makes no network requests."""

import argparse
from importlib import metadata
import json
import re
import sys
from time import perf_counter

from .config import ConfigurationError, Settings, load_settings


SMOKE_PROMPT = "Reply with exactly the word READY and nothing else."
DEFAULT_TIMEOUT_MS = 30_000
RESEARCH_TIMEOUT_MS = 90_000


def create_client(settings: Settings, *, timeout_ms: int = DEFAULT_TIMEOUT_MS):
    from google import genai
    from google.genai import types

    # Explicitly select the Developer API rather than inheriting a Vertex backend.
    # One attempt prevents silent retries; research has its own bounded deadline.
    return genai.Client(
        api_key=settings.api_key,
        vertexai=False,
        http_options=types.HttpOptions(
            timeout=timeout_ms,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def check(settings: Settings) -> int:
    print(f"Python: {sys.version.split()[0]}")
    for package in ("google-genai", "python-dotenv", "langgraph", "ddgs", "trafilatura", "pypdf"):
        print(f"{package}: {metadata.version(package)}")
    print("API key: configured (hidden; validity has not been checked)")
    print(f"Model: {settings.model}")
    print(f"Search backend: {settings.search_backend}")
    print("Local checks passed. No API request was made.")
    print("Before a live call, confirm the key's project is on the Free tier in AI Studio.")
    return 0


def list_models(client) -> int:
    names = sorted({
        model.name.removeprefix("models/")
        for model in client.models.list()
        if model.name and "generateContent" in (model.supported_actions or [])
    })
    print("Models advertising generateContent support:")
    for name in names:
        print(f"  {name}")
    print("This list reports capabilities, not pricing or your available quota.")
    print("Check AI Studio and Google's pricing page before selecting a model.")
    return 0 if names else 1


def smoke(client, settings: Settings) -> int:
    from google.genai import types

    started = perf_counter()
    response = client.models.generate_content(
        model=settings.model,
        contents=SMOKE_PROMPT,
        config=types.GenerateContentConfig(max_output_tokens=256),
    )
    text = (response.text or "").strip()
    # Print a fixed status rather than arbitrary response/error bodies.
    passed = text == "READY"
    print(f"Model: {settings.model}")
    print("Reply: READY" if passed else "Reply did not match the requested READY token.")
    print(f"Elapsed: {perf_counter() - started:.2f}s")
    usage = response.usage_metadata
    if usage:
        print(f"Input tokens: {usage.prompt_token_count}")
        print(f"Total tokens: {usage.total_token_count}")
    print("Connection test passed." if passed else "Request completed, but the response check failed.")
    return 0 if passed else 1


def redacted_provider_message(error: Exception, api_key: str) -> str:
    """Return only the provider's short message, with credentials removed."""
    message = getattr(error, "message", None)
    if not isinstance(message, str):
        return ""
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"AIza[0-9A-Za-z_-]+", "[REDACTED]", message)
    message = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", message)
    message = re.sub(
        r"(?i)((?:api[_-]?key|access[_-]?token|key|authorization)\s*[=:]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s&;,]+)",
        r"\1[REDACTED]", message,
    )
    return " ".join("".join(c if c.isprintable() else " " for c in message).split())[:700]


def explain_error(error: Exception, api_key: str = "", diagnostic: bool = False) -> str:
    summary = error_summary(error)
    # Diagnostics are opt-in and never include raw response bodies or headers.
    code = getattr(error, "code", None)
    if diagnostic and isinstance(code, int) and 400 <= code <= 599:
        message = redacted_provider_message(error, api_key)
        if message:
            return f"{summary}\nGoogle detail (redacted): {message}"
    return summary


def error_summary(error: Exception) -> str:
    # Provider errors can include request details; never print the raw exception.
    code = getattr(error, "code", None)
    if code == 400:
        return "Google API HTTP 400: request rejected. Use --diagnose to inspect the redacted validation message."
    if code == 401:
        return "Google API HTTP 401: authentication failed. Check the configured key."
    if code == 403:
        return "Google API HTTP 403: permission denied. Check project access and model eligibility in AI Studio."
    if code == 404:
        return "Model unavailable. Run list-models and verify a free-tier model in AI Studio."
    if code == 429:
        return "Quota/rate limit reached. Wait for quota to reset; no fallback model was called."
    if code in (500, 502, 503, 504):
        descriptions = {
            500: "Google reported an internal server error",
            502: "Google's gateway could not complete the request",
            503: "Google reported that the service is temporarily unavailable",
            504: "The request exceeded the server deadline",
        }
        return (
            f"Google API HTTP {code}: {descriptions[code]}. "
            "Wait briefly and retry once; no automatic retry or fallback was made."
        )
    return "Connection/setup failed. Check internet access and dependencies. Raw error details were withheld."


def agent_command(client, settings: Settings, question: str, diagnostic: bool = False) -> int:
    from .agent import AgentRequestError, run_agent

    started = perf_counter()
    try:
        result = run_agent(client, settings.model, question)
    except AgentRequestError as error:
        for event in error.events:
            print("Tool: " + json.dumps(event, allow_nan=False))
        print(
            f"Agent stopped on model request {error.request_number} "
            f"after {error.tool_calls} completed tool calls.", file=sys.stderr,
        )
        print(explain_error(error.provider_error, settings.api_key, diagnostic), file=sys.stderr)
        return 1
    print(f"Model: {settings.model}")
    for event in result.events:
        # Display tool activity, not internal model reasoning or raw API bodies.
        print("Tool: " + json.dumps(event, allow_nan=False))
    if result.answer:
        print(f"Answer: {result.answer}")
    else:
        print(f"Run stopped: {result.status}. No final answer produced.")
    print(f"Model calls: {result.model_calls}; tool calls: {result.tool_calls}")
    print(f"Input tokens: {result.input_tokens}; total tokens: {result.total_tokens}")
    print(f"Elapsed: {perf_counter() - started:.2f}s")
    return 0 if result.status == "complete" else 1


def research_command(client, settings: Settings, question: str, diagnostic: bool = False) -> int:
    from .research import execute_research

    def progress(event):
        name = event["tool"]
        if name == "answer_check":
            action = "Correcting once using existing evidence." if event.get("repair_scheduled") else "No further correction scheduled."
            print(f"Answer check: {event['error']} {action}", flush=True)
        elif "error" in event:
            print(f"Action: {name} failed ({event.get('error_code', 'tool_error')}).", flush=True)
        elif name == "search_web":
            print(f"Searched: {event['arguments'].get('query', '')}", flush=True)
        elif name == "read_url":
            result = event.get("result", {})
            print(f"Read [{result.get('source_id', '?')}]: {result.get('url', '')}", flush=True)
        else:
            print(f"Calculated with {name}.", flush=True)

    print(f"Researching with {settings.model} (up to 8 model calls / 12 tool calls; 90s per model request)...", flush=True)
    record, path = execute_research(client, settings, question, on_event=progress, error_formatter=lambda error: explain_error(error, settings.api_key, diagnostic))
    print(f"Status: {record['status']}")
    if record["status"] == "answered":
        print(f"Answer: {record['answer']}")
        for evidence in record["evidence"]:
            page = f", page {evidence['page']}" if evidence["page"] is not None else ""
            print(f"[{evidence['source_id']}{page}] {evidence['title']}\n  {evidence['url']}\n  {evidence['quote']}")
        print("Evidence check: source IDs and quoted text matched; review whether they support the answer.")
    else:
        print(f"Reason: {record['reason']}")
        if record.get("diagnostic"):
            print(record["diagnostic"])
        if diagnostic and record.get("error_type"):
            print(f"Local error type: {record['error_type']}")
    print(f"Model calls: {record['model_calls']}; tool calls: {record['tool_calls']}")
    if record.get("answer_repairs"):
        print(f"Answer corrections: {record['answer_repairs']} (included in model-call count)")
    print(f"Input tokens: {record['input_tokens']}; total tokens: {record['total_tokens']}")
    print(f"Elapsed: {record['elapsed_seconds']:.2f}s")
    print(f"Run record: {path}")
    return 0 if record["status"] == "answered" else 1


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="TraceAgent: setup checks and a bounded tool-using agent.")
    parser.add_argument("command", choices=("check", "list-models", "smoke", "agent", "research"))
    parser.add_argument("question", nargs="?", help="Question for the agent command.")
    parser.add_argument("--diagnose", action="store_true", help="Show a redacted provider validation message on failure.")
    args = parser.parse_args(argv)
    if args.command in ("agent", "research") and not (args.question or "").strip():
        parser.error("agent and research require a quoted question")
    if args.command not in ("agent", "research") and args.question is not None:
        parser.error("only agent and research accept a question")
    if sys.version_info < (3, 11):
        print("Use Python 3.11 or newer (recommended setup: uv sync --python 3.11).", file=sys.stderr)
        return 2
    settings = None
    try:
        settings = load_settings()
        if args.command == "check":
            return check(settings)
        timeout_ms = RESEARCH_TIMEOUT_MS if args.command == "research" else DEFAULT_TIMEOUT_MS
        with create_client(settings, timeout_ms=timeout_ms) as client:
            if args.command == "list-models":
                return list_models(client)
            if args.command == "agent":
                return agent_command(client, settings, args.question, diagnostic=args.diagnose)
            if args.command == "research":
                return research_command(client, settings, args.question, diagnostic=args.diagnose)
            return smoke(client, settings)
    except ConfigurationError as error:
        print(f"Configuration: {error}", file=sys.stderr)
        return 2
    except (ModuleNotFoundError, metadata.PackageNotFoundError):
        print("Dependencies missing. Run uv sync --python 3.11 from the project folder.", file=sys.stderr)
        return 2
    except Exception as error:
        print(explain_error(error, settings.api_key if settings else "", args.diagnose), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
