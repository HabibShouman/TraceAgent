"""Small setup commands. Importing this module makes no network requests."""

import argparse
from importlib import metadata
import sys
from time import perf_counter

from .config import ConfigurationError, Settings, load_settings


SMOKE_PROMPT = "Reply with exactly the word READY and nothing else."


def create_client(settings: Settings):
    from google import genai
    from google.genai import types

    # Explicitly select the Developer API rather than inheriting a Vertex backend.
    # One attempt keeps this setup test from silently retrying generation calls.
    return genai.Client(
        api_key=settings.api_key,
        vertexai=False,
        http_options=types.HttpOptions(
            timeout=30_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def check(settings: Settings) -> int:
    print(f"Python: {sys.version.split()[0]}")
    for package in ("google-genai", "python-dotenv"):
        print(f"{package}: {metadata.version(package)}")
    print("API key: configured (hidden; validity has not been checked)")
    print(f"Model: {settings.model}")
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


def explain_error(error: Exception) -> str:
    # Provider errors can include request details; never print the raw exception.
    code = getattr(error, "code", None)
    if code in (400, 401, 403):
        return "Google rejected the request. Check the API key, project access, and region in AI Studio."
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TraceAgent milestone 1: configure and test Gemini.")
    parser.add_argument("command", choices=("check", "list-models", "smoke"))
    args = parser.parse_args(argv)
    if sys.version_info < (3, 11):
        print("Use Python 3.11 or newer (recommended setup: uv sync --python 3.11).", file=sys.stderr)
        return 2
    try:
        settings = load_settings()
        if args.command == "check":
            return check(settings)
        with create_client(settings) as client:
            if args.command == "list-models":
                return list_models(client)
            return smoke(client, settings)
    except ConfigurationError as error:
        print(f"Configuration: {error}", file=sys.stderr)
        return 2
    except (ModuleNotFoundError, metadata.PackageNotFoundError):
        print("Dependencies missing. Run uv sync --python 3.11 from the project folder.", file=sys.stderr)
        return 2
    except Exception as error:
        print(explain_error(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
