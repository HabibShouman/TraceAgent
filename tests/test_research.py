"""Research correctness and network boundaries, without external API requests."""

from io import BytesIO
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from traceagent.config import Settings
from traceagent.research import ResearchSession, execute_research, save_record
from traceagent.tools import ToolError
from traceagent import web

try:
    from google.genai import types
    from traceagent.agent import run_agent
except ModuleNotFoundError as error:
    if (error.name or "").split(".")[0] not in {"google", "langgraph"}:
        raise
    types = None


SOURCE_TEXT = "The sample mass was exactly seven grams after the final drying procedure. The laboratory used a clean sealed container."
SOURCE_URL = "https://example.org/paper.txt"


def session_fixture():
    return ResearchSession(
        fetcher=Mock(return_value=web.Download(SOURCE_URL, "text/plain", SOURCE_TEXT.encode())),
        searcher=Mock(return_value=[{"title": "Sample report", "href": SOURCE_URL, "body": "A laboratory report."}]),
    )


def final_answer(source="S1", quote=SOURCE_TEXT.split(" The laboratory")[0]):
    return json.dumps({"status": "answered", "answer": "seven grams", "evidence": [{"source_id": source, "quote": quote}], "reason": ""})


class ResearchEvidenceTests(unittest.TestCase):
    def test_search_does_not_create_citable_evidence(self):
        session = session_fixture()
        session.search_web("sample report")
        self.assertEqual(session.sources, {})
        self.assertEqual(session.verify_answer(final_answer())["status"], "evidence_error")

    def test_read_creates_source_and_quote_check_accepts_only_retrieved_words(self):
        session = session_fixture()
        source = session.read_url(SOURCE_URL)
        self.assertEqual(source["source_id"], "S1")
        self.assertEqual(session.verify_answer(final_answer())["status"], "answered")
        self.assertEqual(session.verify_answer(final_answer(quote="The sample mass was nine grams."))["status"], "evidence_error")
        self.assertEqual(session.verify_answer(final_answer(source="S99"))["status"], "evidence_error")

    def test_repeated_search_and_read_use_session_cache(self):
        session = session_fixture()
        session.search_web("sample report")
        session.search_web("sample report")
        first = session.read_url(SOURCE_URL)
        self.assertIs(first, session.read_url(SOURCE_URL))
        session.read_url(SOURCE_URL, focus="laboratory")
        session.fetcher.assert_called_once()
        session.searcher.assert_called_once()

    def test_search_budget_prevents_additional_provider_requests(self):
        session = session_fixture()
        for index in range(4):
            session.search_web(f"sample report query {index}")
        with self.assertRaises(ToolError):
            session.search_web("another query")
        self.assertEqual(session.searcher.call_count, 4)

    @unittest.skipUnless(importlib.util.find_spec("httpx"), "Install HTTPX")
    def test_tavily_basic_request_disables_generated_answers_and_automatic_depth(self):
        import httpx

        def handle(request):
            self.assertEqual(request.headers["authorization"], "Bearer tvly-test-secret")
            payload = json.loads(request.content)
            self.assertEqual(payload["search_depth"], "basic")
            self.assertEqual(payload["max_results"], 2)
            self.assertFalse(payload["include_answer"])
            self.assertFalse(payload["auto_parameters"])
            return httpx.Response(200, json={"results": [{"title": "Report", "url": SOURCE_URL, "content": "Search hint"}]})

        client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        with patch("httpx.Client", return_value=client):
            results = web.tavily_search("sample report", 2, "tvly-test-secret")
        self.assertEqual(results[0]["url"], SOURCE_URL)
        self.assertNotIn("tvly-test-secret", json.dumps(results))

    @unittest.skipUnless(importlib.util.find_spec("httpx"), "Install HTTPX")
    def test_tavily_quota_stops_without_fallback(self):
        import httpx

        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(432, json={"detail": "private provider body"})

        client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        with patch("httpx.Client", return_value=client), self.assertRaises(ToolError) as caught:
            web.tavily_search("sample report", 2, "tvly-test-secret")
        self.assertEqual(caught.exception.code, "search_quota")
        self.assertNotIn("private provider body", str(caught.exception))
        self.assertEqual(len(calls), 1)

    @unittest.skipUnless(importlib.util.find_spec("httpx"), "Install HTTPX")
    def test_serper_uses_search_endpoint_and_returns_only_organic_hints(self):
        import httpx

        def handle(request):
            self.assertEqual(str(request.url), "https://google.serper.dev/search")
            self.assertEqual(request.headers["x-api-key"], "serper-test-secret")
            self.assertEqual(json.loads(request.content), {"q": "sample report", "num": 2})
            return httpx.Response(200, json={
                "answerBox": {"answer": "An unchecked direct answer"},
                "organic": [{"title": "Report", "link": SOURCE_URL, "snippet": "Discovery hint"}] * 3,
            })

        client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        with patch("httpx.Client", return_value=client):
            session = ResearchSession(search_backend="serper", serper_api_key="serper-test-secret")
            result = session.search_web("sample report", 2)
            self.assertIs(result, session.search_web("sample report", 2))
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["url"], SOURCE_URL)
        self.assertEqual(session.search_requests, 1)
        self.assertEqual(session.sources, {})
        self.assertNotIn("unchecked", json.dumps(result))
        self.assertNotIn("serper-test-secret", json.dumps(result))

    @unittest.skipUnless(importlib.util.find_spec("httpx"), "Install HTTPX")
    def test_serper_errors_never_retry_fallback_or_expose_provider_body(self):
        import httpx

        for status, code in ((401, "search_auth"), (403, "search_auth"), (402, "search_quota"), (429, "search_quota"), (503, "search_unavailable")):
            with self.subTest(status=status):
                calls = []
                def handle(request):
                    calls.append(request)
                    return httpx.Response(status, json={"detail": "private provider body serper-test-secret"})
                client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
                with patch("httpx.Client", return_value=client), patch.object(web, "search") as fallback, self.assertRaises(ToolError) as caught:
                    web.serper_search("sample report", 2, "serper-test-secret")
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("private provider body", str(caught.exception))
                self.assertNotIn("serper-test-secret", str(caught.exception))
                self.assertEqual(len(calls), 1)
                fallback.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec("httpx"), "Install HTTPX")
    def test_serper_malformed_responses_and_transport_errors_are_structured(self):
        import httpx

        for response in (httpx.Response(200, text="not JSON"), httpx.Response(200, json={"organic": {}}), httpx.Response(200, content=b" " * (1024 * 1024 + 1))):
            with self.subTest(response=response):
                client = httpx.Client(transport=httpx.MockTransport(lambda request: response), trust_env=False)
                with patch("httpx.Client", return_value=client), self.assertRaises(ToolError) as caught:
                    web.serper_search("sample report", 2, "serper-test-secret")
                self.assertEqual(caught.exception.code, "search_response")
        with patch("httpx.Client") as constructor:
            constructor.return_value.__enter__.return_value.post.side_effect = httpx.ConnectTimeout("serper-test-secret")
            with self.assertRaises(ToolError) as caught:
                web.serper_search("sample report", 2, "serper-test-secret")
        self.assertEqual(caught.exception.code, "search_unavailable")
        self.assertNotIn("serper-test-secret", str(caught.exception))

    def test_rejects_bad_output_and_excessive_quotes(self):
        session = session_fixture()
        session.read_url(SOURCE_URL)
        for text in ("answer", "[]", "{}", '{"status":"answered","answer":1,"evidence":[]}'):
            with self.subTest(text=text):
                self.assertEqual(session.verify_answer(text)["status"], "format_error")
        value = json.loads(final_answer())
        value["evidence"] *= 3
        self.assertEqual(session.verify_answer(json.dumps(value))["status"], "evidence_error")

    def test_unresolved_and_fenced_json_have_clear_statuses(self):
        session = session_fixture()
        session.read_url(SOURCE_URL)
        self.assertEqual(session.verify_answer("```json\n" + final_answer() + "\n```")["status"], "answered")
        self.assertEqual(session.verify_answer('{"status":"unresolved","reason":"Source unavailable"}')["answer"], "")

    def test_quote_limit_applies_across_ids_for_the_same_url(self):
        session = session_fixture()
        session.read_url(SOURCE_URL)
        session.read_url(SOURCE_URL, focus="laboratory")
        value = {"status": "answered", "answer": "seven grams", "evidence": [
            {"source_id": "S1", "quote": SOURCE_TEXT},
            {"source_id": "S2", "quote": SOURCE_TEXT},
        ]}
        self.assertEqual(session.verify_answer(json.dumps(value))["status"], "evidence_error")

    def test_focus_selects_relevant_pdf_page_and_reports_truncation(self):
        document = {"pages": [{"page": 1, "text": "Unrelated material. " * 1500}, {"page": 2, "text": SOURCE_TEXT}]}
        selected, truncated = web.passages(document, "sample mass", limit=500)
        self.assertTrue(truncated)
        self.assertTrue(any(passage["page"] == 2 and "seven grams" in passage["text"] for passage in selected))

    def test_saved_record_redacts_key_recursively_and_handles_non_finite_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_record({"question": "test-secret", "actions": [{"result": "Bearer other-secret", "a": float("nan")} ]}, api_key="test-secret", directory=Path(directory))
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("test-secret", text)
            self.assertNotIn("other-secret", text)
            self.assertEqual(json.loads(text)["actions"][0]["a"], "[non-finite number]")


class PublicWebTests(unittest.TestCase):
    def test_rejects_local_credential_and_non_http_urls(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1/", "http://[::1]/", "http://10.0.0.1/", "https://localhost/", "https://example.org:8443/", "https://user:password@example.org/", "https://example.org/?api_key=secret"):
            with self.subTest(url=url), self.assertRaises(ToolError):
                web.public_url(url)

    def test_dns_resolution_rejects_mixed_public_and_private_addresses(self):
        resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in ("93.184.216.34", "127.0.0.1")]
        with patch("socket.getaddrinfo", return_value=resolved), self.assertRaises(ToolError):
            web.resolve_public("example.org", 443)

    def test_metadata_keeps_document_links_and_title(self):
        metadata = web.PageMetadata("https://example.org/article")
        metadata.feed('<title>Sample report</title><a href="/paper.pdf">Original paper</a>')
        self.assertEqual(metadata.title, "Sample report")
        self.assertEqual(metadata.links[0]["url"], "https://example.org/paper.pdf")

    @unittest.skipUnless(importlib.util.find_spec("urllib3"), "Install urllib3")
    def test_download_pins_public_ip_and_validates_tls_hostname(self):
        response = Mock(status=200, headers={"Content-Type": "text/plain"})
        response.stream.return_value = [b"source text"]
        pool = Mock()
        pool.urlopen.return_value = response
        with patch.object(web, "resolve_public", return_value="93.184.216.34"), \
             patch.object(web, "proxy_for", return_value=None), \
             patch("urllib3.HTTPSConnectionPool", return_value=pool) as constructor:
            item = web.download("https://example.org/paper.txt")
        self.assertEqual(item.data, b"source text")
        self.assertEqual(constructor.call_args.kwargs["host"], "93.184.216.34")
        self.assertEqual(constructor.call_args.kwargs["server_hostname"], "example.org")
        self.assertEqual(constructor.call_args.kwargs["assert_hostname"], "example.org")
        self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
        self.assertFalse(pool.urlopen.call_args.kwargs["retries"])

    @unittest.skipUnless(importlib.util.find_spec("urllib3"), "Install urllib3")
    def test_redirect_to_private_address_is_blocked_before_next_request(self):
        response = Mock(status=302, headers={"Location": "http://127.0.0.1/private"})
        pool = Mock()
        pool.urlopen.return_value = response
        with patch.object(web, "resolve_public", return_value="93.184.216.34"), \
             patch.object(web, "proxy_for", return_value=None), \
             patch("urllib3.HTTPSConnectionPool", return_value=pool), self.assertRaises(ToolError):
            web.download(SOURCE_URL)
        pool.urlopen.assert_called_once()

    def test_proxy_routing_uses_hostname_after_public_dns_validation(self):
        with patch.object(web, "resolve_public", return_value="93.184.216.34") as resolve, \
             patch.object(web, "proxy_for", return_value="socks5h://proxy.example:1080"), \
             patch.object(web, "proxy_get", return_value=(200, {"content-type": "text/plain"}, b"source text")) as request:
            self.assertEqual(web.download(SOURCE_URL).data, b"source text")
        resolve.assert_called_once_with("example.org", 443)
        request.assert_called_once_with(SOURCE_URL, "socks5h://proxy.example:1080")

    @unittest.skipUnless(importlib.util.find_spec("trafilatura"), "Install trafilatura")
    def test_html_extraction_reads_article_and_retains_pdf_link(self):
        html = ('<html><head><title>Sample study</title></head><body><nav>Navigation</nav><article><h1>Sample study</h1>' + (f'<p>{SOURCE_TEXT}</p>' * 6) + '<a href="/study.pdf">Full paper</a></article></body></html>')
        document = web.parse_document(web.Download(SOURCE_URL, "text/html", html.encode()))
        self.assertIn("seven grams", document["pages"][0]["text"])
        self.assertEqual(document["title"], "Sample study")
        self.assertEqual(document["links"][0]["url"], "https://example.org/study.pdf")

    @unittest.skipUnless(importlib.util.find_spec("pypdf"), "Install pypdf")
    def test_pdf_worker_extracts_text_and_page_locations(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 72 720 Td (The sample mass was seven grams.) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        buffer = BytesIO()
        writer.write(buffer)
        document = web.bounded_worker(web._pdf_text, (buffer.getvalue(),), timeout=20)
        self.assertEqual(document["pages"][0]["page"], 1)
        self.assertIn("seven grams", document["pages"][0]["text"])


@unittest.skipIf(types is None, "Install model/graph dependencies")
class ResearchWorkflowTests(unittest.TestCase):
    def test_selected_serper_backend_and_credentials_are_handled_in_run_record(self):
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(side_effect=[
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="search_web", args={"query": "sample report"}))]))]),
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text='{"status":"unresolved","reason":"serper-test-secret"}')]))]),
        ])))
        settings = Settings(api_key="test-secret", search_backend="serper", serper_api_key="serper-test-secret")
        with tempfile.TemporaryDirectory() as directory, patch.object(web, "serper_search", return_value=[]) as searcher:
            record, path = execute_research(client, settings, "Find a source.", directory=Path(directory))
            saved = path.read_text(encoding="utf-8")
        searcher.assert_called_once_with("sample report", 5, api_key="serper-test-secret")
        self.assertEqual(record["search_backend"], "serper:search")
        self.assertEqual(record["search_requests"], 1)
        self.assertEqual(record["search_credits_upper_bound"], 1)
        self.assertNotIn("serper-test-secret", saved)
        config = client.models.generate_content.call_args_list[0].kwargs["config"]
        self.assertNotIn("serper-test-secret", str(config.tools))
        self.assertEqual(config.thinking_config.thinking_level, types.ThinkingLevel.LOW)
        self.assertEqual(config.max_output_tokens, 4096)
        self.assertEqual(record["thinking_level"], "low")

    def test_search_read_answer_and_record_complete_without_network(self):
        def response(*parts):
            return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])

        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(side_effect=[
            response(types.Part(function_call=types.FunctionCall(name="search_web", args={"query": "sample mass report"}))),
            response(types.Part(function_call=types.FunctionCall(name="read_url", args={"url": SOURCE_URL, "focus": "sample mass"}))),
            response(types.Part(text=final_answer())),
        ])))
        session = session_fixture()
        with tempfile.TemporaryDirectory() as directory:
            record, path = execute_research(client, Settings(api_key="test-secret"), "What was the sample mass?", session=session, directory=Path(directory))
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "answered")
        self.assertEqual(record["answer"], "seven grams")
        self.assertEqual((record["model_calls"], record["tool_calls"]), (3, 2))
        self.assertEqual(record["evidence_check"], "passed")
        self.assertFalse(record["factual_entailment_checked"])
        self.assertEqual(saved["sources"][0]["source_id"], "S1")
        self.assertEqual(saved["actions"][1]["result"]["source_id"], "S1")
        self.assertNotIn("contents", saved)
        first = client.models.generate_content.call_args_list[0].kwargs["config"]
        names = {declaration.name for declaration in first.tools[0].function_declarations}
        self.assertTrue({"search_web", "read_url", "multiply", "add"}.issubset(names))

    def test_output_limit_preserves_sources_calculation_usage_and_incomplete_candidate(self):
        partial = '{"status":"answered","answer":"21","evidence":[{'
        def reply(part, finish=types.FinishReason.STOP):
            return types.GenerateContentResponse(
                candidates=[types.Candidate(content=types.Content(role="model", parts=[part]), finish_reason=finish)],
                usage_metadata=types.GenerateContentResponseUsageMetadata(
                    prompt_token_count=20, candidates_token_count=8,
                    thoughts_token_count=40, total_token_count=68,
                ),
            )
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(side_effect=[
            reply(types.Part(function_call=types.FunctionCall(name="read_url", args={"url": SOURCE_URL}))),
            reply(types.Part(function_call=types.FunctionCall(name="multiply", args={"a": 7, "b": 3}))),
            reply(types.Part(text=partial), finish=types.FinishReason.MAX_TOKENS),
        ])))
        with tempfile.TemporaryDirectory() as directory:
            record, path = execute_research(client, Settings(api_key="test-secret"), "Find and multiply the mass.", session=session_fixture(), directory=Path(directory))
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "output_limit")
        self.assertEqual(record["answer"], "")
        self.assertEqual(record["evidence_check"], "not_run")
        self.assertIn("MAX_TOKENS", record["reason"])
        self.assertEqual(record["last_finish_reason"], "MAX_TOKENS")
        self.assertEqual(saved["candidate_response"], partial)
        self.assertEqual(saved["sources"][0]["source_id"], "S1")
        self.assertEqual(saved["actions"][1]["result"], 21.0)
        self.assertEqual(saved["reported_thought_tokens"], 120)
        self.assertEqual(len(saved["model_responses"]), 3)
        self.assertEqual(client.models.generate_content.call_count, 3)
        self.assertEqual(record["limits"]["output_tokens_per_call"], 4096)

    def test_invalid_json_with_normal_finish_is_still_rejected_without_repair(self):
        partial = '{"status":"answered","answer":"21","evidence":[{'
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(return_value=
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=partial)]), finish_reason=types.FinishReason.STOP)])
        )))
        with tempfile.TemporaryDirectory() as directory:
            record, _ = execute_research(client, Settings(api_key="test-secret"), "Answer.", session=session_fixture(), directory=Path(directory))
        self.assertEqual(record["status"], "format_error")
        self.assertEqual(record["last_finish_reason"], "STOP")
        self.assertEqual(record["candidate_response"], partial)
        self.assertEqual(record["answer"], "")
        client.models.generate_content.assert_called_once()

    def test_unverified_models_keep_their_default_thinking_setting(self):
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(return_value=
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text='{"status":"unresolved","reason":"No source."}')]))])
        )))
        with tempfile.TemporaryDirectory() as directory:
            record, _ = execute_research(client, Settings(api_key="test-secret", model="gemini-2.5-flash"), "Find a source.", session=session_fixture(), directory=Path(directory))
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertIsNone(config.thinking_config)
        self.assertEqual(record["thinking_level"], "model_default")
        self.assertEqual(config.max_output_tokens, 4096)

    def test_provider_failure_is_saved_without_raw_error_body(self):
        error = RuntimeError("test-secret in raw provider body")
        error.code = 503
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(side_effect=error)))
        with tempfile.TemporaryDirectory() as directory:
            record, path = execute_research(client, Settings(api_key="test-secret"), "Find a source.", session=session_fixture(), directory=Path(directory))
            text = path.read_text(encoding="utf-8")
        self.assertEqual(record["status"], "provider_error")
        self.assertEqual(record["failed_request_number"], 1)
        self.assertIn("HTTP 503", record["reason"])
        self.assertNotIn("test-secret", text)

    def test_tool_failures_are_observations_and_do_not_abort_graph(self):
        session = session_fixture()
        session.fetcher.side_effect = ToolError("source_unavailable", "The source could not be read.")
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(side_effect=[
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="read_url", args={"url": SOURCE_URL}))]))]),
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text='{"status":"unresolved","reason":"Source unavailable"}')]))]),
        ])))
        with tempfile.TemporaryDirectory() as directory:
            record, _ = execute_research(client, Settings(api_key="test-secret"), "Read the source.", session=session, directory=Path(directory))
        self.assertEqual(record["status"], "unresolved")
        self.assertEqual(record["actions"][0]["error_code"], "source_unavailable")
        self.assertIn("elapsed_ms", record["actions"][0])


if __name__ == "__main__":
    unittest.main()
