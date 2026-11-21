"""Fabricated research tasks over the real SDK's offline HTTP transport."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from traceagent.config import Settings
from traceagent.research import ResearchSession, execute_research
from traceagent.tools import ToolError
from traceagent.web import Download

try:
    import httpx
    from google import genai
    from google.genai import types
    from traceagent.agent import run_agent
except ModuleNotFoundError:
    httpx = None


URL = "https://example.org/instrument-report.txt"
TEXT = "The calibration sample contains seven grams of copper."


class SessionAvailabilityTests(unittest.TestCase):
    def test_filtered_or_empty_results_do_not_force_a_read(self):
        for results in ([], [{"href": "https://huggingface.co/datasets/example/answers", "body": "Excluded data."}]):
            with self.subTest(results=results):
                session = ResearchSession(searcher=Mock(return_value=results), benchmark_mode=True)
                session.search_web("original calibration report")
                self.assertEqual(session.tool_restrictions(), {})

    def test_invalid_read_does_not_consume_search_allowance_or_fetch_private_url(self):
        session = ResearchSession(searcher=Mock(return_value=[{"href": URL}]), fetcher=Mock())
        session.search_web("original calibration report")
        for url, focus in (("http://127.0.0.1/report", ""), (URL, "x" * 301)):
            with self.subTest(url=url), self.assertRaises(ToolError):
                session.read_url(url, focus)
            self.assertEqual(session.tool_restrictions(), {})
            self.assertEqual(session.search_requests, 1)
        session.fetcher.assert_not_called()

    def test_cached_search_updates_allowance_without_rewriting_old_observations(self):
        session = ResearchSession(searcher=Mock(return_value=[{"href": URL}]))
        first = session.search_web("initial instrument report")
        session.search_web("refined instrument report")
        cached = session.search_web("initial instrument report")
        self.assertEqual(first["search_requests_remaining"], 3)
        self.assertEqual(cached["search_requests_remaining"], 2)
        self.assertEqual(cached["results"], first["results"])
        self.assertEqual(session.searcher.call_count, 2)


@unittest.skipIf(httpx is None, "Install SDK dependencies")
class AvailabilityTransportTests(unittest.TestCase):
    def client(self, handle):
        return genai.Client(api_key="offline-only-key", vertexai=False, http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
            client_args={"transport": httpx.MockTransport(handle), "trust_env": False},
        ))

    def reply(self, *parts):
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": list(parts)}, "finishReason": "STOP"}]})

    def call(self, name, **args):
        return {"functionCall": {"name": name, "args": args, "id": "call-1"}, "thoughtSignature": "c2ln"}

    def finish(self, status="answered"):
        return {"text": json.dumps({"status": status, "answer": "seven grams" if status == "answered" else "", "evidence": [{"source_id": "S1", "quote": TEXT}] if status == "answered" else [], "reason": "" if status == "answered" else "No source passages were read."})}

    def names(self, body):
        return {d["name"] for tool in body.get("tools", []) for d in tool.get("functionDeclarations", [])}

    def session(self, search_results=None):
        return ResearchSession(
            searcher=Mock(return_value=[{"href": URL, "title": "Instrument report"}] if search_results is None else search_results),
            fetcher=Mock(return_value=Download(URL, "text/plain", TEXT.encode())),
        )

    def run_research(self, session, handle, max_calls=8):
        with tempfile.TemporaryDirectory() as temporary, self.client(handle) as client:
            record, _ = execute_research(client, Settings(api_key="offline-only-key"), "Find the mass in the instrument report.", session=session, directory=Path(temporary), max_model_calls=max_calls)
        return record

    def test_search_read_answer_keeps_tools_available_and_retains_call_protocol(self):
        requests = []
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) == 1:
                self.assertIn("search_web", self.names(body))
                return self.reply(self.call("search_web", query="original calibration report"))
            if len(requests) == 2:
                self.assertIn("search_web", self.names(body))
                self.assertIn("read_url", self.names(body))
                self.assertEqual(body["contents"][1]["parts"][0]["thoughtSignature"], "c2ln")
                self.assertEqual(body["contents"][2]["parts"][0]["functionResponse"]["id"], "call-1")
                return self.reply(self.call("read_url", url=URL))
            self.assertIn("search_web", self.names(body))
            return self.reply(self.finish())
        session = self.session(); record = self.run_research(session, handle)
        self.assertEqual(record["status"], "answered")
        self.assertEqual((record["model_calls"], record["tool_calls"]), (3, 2))
        self.assertEqual(record["model_responses"][1]["tool_restrictions"], {})
        session.searcher.assert_called_once(); session.fetcher.assert_called_once()

    def test_irrelevant_results_allow_refinement_before_any_read(self):
        requests = []
        session = self.session()
        session.searcher.side_effect = [
            [{"href": "https://example.org/staff-directory", "title": "Staff profile"}],
            [{"href": URL, "title": "Instrument measurement report"}],
        ]
        plan = [self.call("search_web", query="broad instrument report"),
                self.call("search_web", query="instrument calibration measured mass"),
                self.call("read_url", url=URL), self.finish()]
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) == 2:
                self.assertIn("search_web", self.names(body))
                session.fetcher.assert_not_called()
            return self.reply(plan[len(requests) - 1])
        record = self.run_research(session, handle, max_calls=4)
        self.assertEqual(record["status"], "answered")
        self.assertEqual((record["model_calls"], record["search_requests"]), (4, 2))
        self.assertTrue(all("error" not in x for x in record["actions"]))
        session.fetcher.assert_called_once_with(URL)

    def test_four_empty_searches_remove_search_but_keep_read_available(self):
        requests = []
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            step = len(requests)
            if step <= 4:
                self.assertIn("search_web", self.names(body))
                return self.reply(self.call("search_web", query=f"original calibration query {step}"))
            self.assertNotIn("search_web", self.names(body))
            self.assertIn("read_url", self.names(body))
            return self.reply(self.call("read_url", url=URL)) if step == 5 else self.reply(self.finish())
        session = self.session([]); record = self.run_research(session, handle)
        self.assertEqual(record["status"], "answered")
        self.assertEqual((len(requests), session.searcher.call_count, session.search_requests), (6, 4, 4))
        self.assertEqual(record["model_responses"][-1]["tool_restrictions"], {"search_web": "search_budget"})

    def test_failed_read_keeps_search_available_and_does_not_create_evidence(self):
        requests = []
        session = self.session()
        session.fetcher.side_effect = [ToolError("source_http_error", "The source returned HTTP 403."), Download(URL, "text/plain", TEXT.encode())]
        plan = [self.call("search_web", query="original calibration report"), self.call("read_url", url=URL), self.call("search_web", query="alternative calibration report"), self.call("read_url", url=URL), self.finish()]
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) == 3:
                self.assertIn("search_web", self.names(body))
                self.assertEqual(session.sources, {})
            return self.reply(plan[len(requests) - 1])
        record = self.run_research(session, handle)
        self.assertEqual(record["status"], "answered")
        self.assertEqual(len(record["sources"]), 1)
        self.assertEqual(record["actions"][1]["error_code"], "source_http_error")
        self.assertEqual(session.searcher.call_count, 2)

    def test_batch_rechecks_budget_before_fifth_search_provider_request(self):
        requests = []
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) == 1:
                return self.reply(*(self.call("search_web", query=f"calibration report query {i}") for i in range(5)))
            if len(requests) == 2:
                self.assertNotIn("search_web", self.names(body))
                return self.reply(self.call("read_url", url=URL))
            return self.reply(self.finish())
        session = self.session(); record = self.run_research(session, handle)
        self.assertEqual(record["status"], "answered")
        denied = record["actions"][4]
        self.assertEqual(denied["error_code"], "tool_unavailable")
        self.assertEqual(denied["restriction_reason"], "search_budget")
        self.assertIn("read_url", denied["available_tools"])
        self.assertNotIn("search_web", denied["available_tools"])
        self.assertEqual((session.searcher.call_count, record["tool_calls"]), (4, 6))

    def test_undeclared_search_cannot_execute_and_finalization_still_has_hard_cap(self):
        requests = []
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) <= 5:
                if len(requests) == 5:
                    self.assertNotIn("search_web", self.names(body))
                return self.reply(self.call("search_web", query=f"calibration query {len(requests)}"))
            self.assertFalse(body.get("tools"))
            self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
            return self.reply(self.finish("unresolved"))
        session = self.session([]); record = self.run_research(session, handle, max_calls=6)
        self.assertEqual(record["status"], "unresolved")
        self.assertEqual(record["sources"], [])
        self.assertEqual(record["actions"][4]["error_code"], "tool_unavailable")
        self.assertEqual(record["actions"][4]["restriction_reason"], "search_budget")
        self.assertIn("read_url", record["actions"][4]["available_tools"])
        self.assertEqual((len(requests), session.searcher.call_count), (6, 4))

    def test_available_search_does_not_force_reading_or_fabricating_an_answer(self):
        requests = []
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) == 1:
                return self.reply(self.call("search_web", query="original calibration report"))
            self.assertIn("search_web", self.names(body))
            return self.reply(self.finish("unresolved"))
        session = self.session(); record = self.run_research(session, handle)
        self.assertEqual(record["status"], "unresolved")
        self.assertEqual(record["model_calls"], 2)
        session.fetcher.assert_not_called()

    def test_empty_available_set_is_omitted_from_serialized_request(self):
        from traceagent.tools import multiply
        def handle(request):
            body = json.loads(request.content)
            self.assertFalse(body.get("tools"))
            return self.reply({"text": "No external tool is needed."})
        with self.client(handle) as client:
            result = run_agent(client, "test-model", "Explain the supplied input.", tools=[multiply], tool_policy=lambda: {"multiply": "unavailable"})
        self.assertEqual(result.model_events[0]["available_tools"], [])
        self.assertEqual(result.tool_calls, 0)


if __name__ == "__main__":
    unittest.main()
