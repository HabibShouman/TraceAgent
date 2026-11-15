"""Offline checks for credential handling and API-call boundaries."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from traceagent.config import ConfigurationError, Settings
from traceagent import __main__ as cli

try:
    from google.genai import types
except ImportError:
    types = None


class SetupTests(unittest.TestCase):
    def test_requires_real_configuration(self):
        for key in (None, "", "   ", "paste_your_key_here"):
            with self.subTest(key=key), self.assertRaises(ConfigurationError):
                Settings.from_mapping({"GEMINI_API_KEY": key})

    def test_supports_existing_google_key_without_disclosing_it(self):
        settings = Settings.from_mapping({"GOOGLE_API_KEY": "test-secret"})
        self.assertEqual(settings.api_key, "test-secret")
        self.assertNotIn("test-secret", repr(settings))

    def test_rejects_conflicting_project_keys(self):
        with self.assertRaises(ConfigurationError) as context:
            Settings.from_mapping({"GEMINI_API_KEY": "secret-a", "GOOGLE_API_KEY": "secret-b"})
        self.assertNotIn("secret-a", str(context.exception))
        self.assertNotIn("secret-b", str(context.exception))

    def test_check_does_not_create_network_client(self):
        settings = Settings(api_key="test-secret")
        output = StringIO()
        with patch.object(cli, "load_settings", return_value=settings), \
             patch.object(cli.metadata, "version", return_value="test"), \
             patch.object(cli, "create_client") as create_client, \
             redirect_stdout(output):
            self.assertEqual(cli.main(["check"]), 0)
        create_client.assert_not_called()
        self.assertNotIn("test-secret", output.getvalue())

    def test_network_error_does_not_leak_credentials_or_retry(self):
        output = StringIO()
        settings = Settings(api_key="test-secret")
        with patch.object(cli, "load_settings", return_value=settings), \
             patch.object(cli, "create_client", side_effect=RuntimeError("test-secret")) as create_client, \
             redirect_stderr(output):
            self.assertEqual(cli.main(["smoke"]), 1)
        self.assertEqual(create_client.call_count, 1)
        self.assertNotIn("test-secret", output.getvalue())

    def test_quota_error_explains_failure_without_provider_body(self):
        class QuotaError(Exception):
            code = 429

        message = cli.explain_error(QuotaError("test-secret"))
        self.assertIn("Quota", message)
        self.assertNotIn("test-secret", message)

    def test_server_errors_report_status_without_provider_body(self):
        for code in (500, 502, 503, 504):
            with self.subTest(code=code):
                error = RuntimeError("test-secret in provider response body")
                error.code = code
                message = cli.explain_error(error)
                self.assertIn(f"HTTP {code}:", message)
                self.assertNotIn("test-secret", message)

    def test_non_http_error_code_cannot_leak_provider_data(self):
        error = RuntimeError("provider body")
        error.code = "test-secret"
        self.assertNotIn("test-secret", cli.explain_error(error))

    def test_client_error_statuses_are_distinct(self):
        for code, expected in ((400, "request rejected"), (401, "authentication failed"), (403, "permission denied")):
            with self.subTest(code=code):
                error = RuntimeError("provider body")
                error.code = code
                self.assertIn(f"HTTP {code}", cli.explain_error(error))
                self.assertIn(expected, cli.explain_error(error))

    def test_opt_in_diagnostic_redacts_credentials_and_excludes_raw_body(self):
        error = RuntimeError("raw-body-secret")
        error.code = 400
        error.message = (
            "Unknown field responseJsonSchema. Local secret test-secret "
            "key=another-secret&next=1 Authorization: Bearer token-secret "
            "api_key='quoted-secret' AIzaExampleGoogleKey0123456789"
        )
        plain = cli.explain_error(error, api_key="test-secret")
        detailed = cli.explain_error(error, api_key="test-secret", diagnostic=True)
        self.assertNotIn("Unknown field", plain)
        self.assertIn("Unknown field responseJsonSchema", detailed)
        for secret in ("raw-body-secret", "test-secret", "another-secret", "token-secret", "quoted-secret", "AIzaExampleGoogleKey0123456789"):
            self.assertNotIn(secret, detailed)

    def test_diagnostic_is_bounded_and_single_line(self):
        error = RuntimeError("raw body")
        error.message = "validation\n\t" + "x" * 2000
        result = cli.redacted_provider_message(error, "")
        self.assertLessEqual(len(result), 700)
        self.assertNotIn("\n", result)
        self.assertNotIn("\t", result)

    def test_model_listing_filters_capabilities_and_deduplicates(self):
        client = Mock()
        client.models.list.return_value = [
            SimpleNamespace(name="models/z-model", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/a-model", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/z-model", supported_actions=["generateContent"]),
            SimpleNamespace(name="models/embed-only", supported_actions=["embedContent"]),
        ]
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.list_models(client), 0)
        self.assertLess(output.getvalue().index("a-model"), output.getvalue().index("z-model"))
        self.assertEqual(output.getvalue().count("z-model"), 1)
        self.assertNotIn("embed-only", output.getvalue())


@unittest.skipIf(types is None, "Install SDK dependencies to exercise request configuration.")
class SDKBoundaryTests(unittest.TestCase):
    def test_real_sdk_client_constructs_without_an_api_request(self):
        with patch("httpx.Client.request", side_effect=AssertionError("Unexpected API request")):
            with cli.create_client(Settings(api_key="test-secret")) as client:
                self.assertIsNotNone(client.models)

    def test_client_pins_developer_backend_and_one_attempt(self):
        with patch("google.genai.Client") as constructor:
            cli.create_client(Settings(api_key="test-secret"))
        options = constructor.call_args.kwargs
        self.assertFalse(options["vertexai"])
        self.assertEqual(options["http_options"].timeout, 30_000)
        self.assertEqual(options["http_options"].retry_options.attempts, 1)

    def test_smoke_makes_one_bounded_request_to_configured_model(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            text="READY", usage_metadata=None,
        )
        with redirect_stdout(StringIO()):
            self.assertEqual(cli.smoke(client, Settings(api_key="test-secret", model="test-model")), 0)
        client.models.generate_content.assert_called_once()
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(request["contents"], cli.SMOKE_PROMPT)
        self.assertEqual(request["config"].max_output_tokens, 256)
        self.assertFalse(request["config"].tools)

    def test_smoke_treats_empty_reply_as_failure(self):
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(text=None, usage_metadata=None)
        with redirect_stdout(StringIO()):
            self.assertEqual(cli.smoke(client, Settings(api_key="test-secret")), 1)


if __name__ == "__main__":
    unittest.main()
