"""Observe finish/correction requests through the actual SDK with fake transport."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from traceagent.config import Settings
from traceagent.research import FINAL_RESPONSE_SCHEMA, ResearchSession, execute_research
from traceagent.web import Download

try:
    import httpx
    from google import genai
    from google.genai import types
    from traceagent.agent import run_agent
except ModuleNotFoundError:
    httpx = None


URL = "https://example.org/original-report.txt"
SOURCE = 'The report label is "delta" and the measured count is seven.'


class FocusNoticeTests(unittest.TestCase):
    def test_missing_focus_is_explicit_and_does_not_claim_the_source_has_no_answer(self):
        session = ResearchSession(fetcher=Mock(return_value=Download(URL, "text/plain", SOURCE.encode())))
        missing = session.read_url(URL, focus="unmatchedword")
        self.assertEqual(missing["focus_terms_matched"], [])
        self.assertIn("does not establish", missing["focus_notice"])
        found = session.read_url(URL, focus="report delta")
        self.assertEqual(found["focus_terms_matched"], ["delta", "report"])
        self.assertNotIn("focus_notice", found)
        session.fetcher.assert_called_once()


@unittest.skipIf(httpx is None, "Install model/graph dependencies")
class FinalizationTests(unittest.TestCase):
    def make_client(self, handle):
        return genai.Client(api_key="offline-only-key", vertexai=False, http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
            client_args={"transport": httpx.MockTransport(handle), "trust_env": False},
        ))

    def reply(self, parts, finish="STOP"):
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": finish}]})

    def session(self):
        return ResearchSession(fetcher=Mock(return_value=Download(URL, "text/plain", SOURCE.encode())), searcher=Mock(return_value=[]))

    def final(self, source="S1", quote=SOURCE):
        return json.dumps({"status": "answered", "answer": "seven", "evidence": [{"source_id": source, "quote": quote}], "reason": ""})

    def assert_schema_without_tools(self, body):
        self.assertFalse(body.get("tools"))
        self.assertFalse(body.get("toolConfig"))
        generation = body["generationConfig"]
        self.assertEqual(generation["responseMimeType"], "application/json")
        self.assertEqual(generation["responseJsonSchema"], FINAL_RESPONSE_SCHEMA)

    def test_eighth_request_finishes_from_observations_instead_of_selecting_more_tools(self):
        requests, progress = [], []
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            step = len(requests)
            if step == 1:
                return self.reply([{"functionCall": {"name": "read_url", "args": {"url": URL}, "id": "source-1"}, "thoughtSignature": "c2ln"}])
            if step < 8:
                return self.reply([{"functionCall": {"name": "multiply", "args": {"a": 1, "b": 1}, "id": f"calc-{step}"}, "thoughtSignature": "c2ln"}])
            self.assert_schema_without_tools(body)
            self.assertIn("Finish now", body["contents"][-1]["parts"][0]["text"])
            self.assertEqual(body["contents"][1]["parts"][0]["thoughtSignature"], "c2ln")
            self.assertEqual(body["contents"][2]["parts"][0]["functionResponse"]["id"], "source-1")
            return self.reply([{"text": self.final()}])
        session = self.session()
        with tempfile.TemporaryDirectory() as temporary, self.make_client(handle) as client:
            record, path = execute_research(client, Settings(api_key="offline-only-key"), "Read the report and provide its measured count.", session=session, directory=Path(temporary), on_event=progress.append)
        self.assertEqual(record["status"], "answered")
        self.assertEqual((record["model_calls"], record["tool_calls"]), (8, 7))
        self.assertEqual(len(requests), 8)
        self.assertEqual(record["model_responses"][-1]["phase"], "finalization")
        self.assertEqual(record["answer_repairs"], 0)
        self.assertEqual([e["trigger"] for e in progress if e["tool"] == "answer_finalize"], ["last_request"])
        session.fetcher.assert_called_once()

    def test_tool_request_during_forced_finish_is_rejected_without_execution(self):
        requests = []
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 2:
                self.assert_schema_without_tools(body)
            return self.reply([{"functionCall": {"name": "multiply", "args": {"a": 2, "b": 3}}, "thoughtSignature": "c2ln"}])
        with tempfile.TemporaryDirectory() as temporary, self.make_client(handle) as client:
            record, _ = execute_research(client, Settings(api_key="offline-only-key"), "Multiply the supplied numbers.", session=self.session(), directory=Path(temporary), max_model_calls=2)
        self.assertEqual(record["status"], "finalization_tool_request")
        self.assertEqual((record["model_calls"], record["tool_calls"]), (2, 1))
        self.assertEqual(record["answer"], "")

    def test_finish_can_report_unresolved_without_fabricating_evidence(self):
        requests = []
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                return self.reply([{"functionCall": {"name": "search_web", "args": {"query": "original measurement report"}}, "thoughtSignature": "c2ln"}])
            self.assert_schema_without_tools(body)
            return self.reply([{"text": json.dumps({"status": "unresolved", "answer": "", "evidence": [], "reason": "No independent source was opened."})}])
        with tempfile.TemporaryDirectory() as temporary, self.make_client(handle) as client:
            record, _ = execute_research(client, Settings(api_key="offline-only-key"), "Find an external measurement.", session=self.session(), directory=Path(temporary), max_model_calls=2)
        self.assertEqual(record["status"], "unresolved")
        self.assertEqual(record["sources"], [])
        self.assertEqual(record["answer"], "")
        self.assertEqual(len(requests), 2)

    def test_one_schema_correction_handles_embedded_quotes_without_new_tools(self):
        question = 'Use this supplied observation: the count labelled "delta" is seven.'
        malformed = '{"status":"answered","answer":"seven","evidence":[{"source_id":"Q1","quote":"' + question + '"}],"reason":""}'
        requests = []
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                return self.reply([{"text": malformed, "thoughtSignature": "c2ln"}])
            self.assert_schema_without_tools(body)
            self.assertEqual(body["contents"][-2]["parts"][0]["text"], malformed)
            return self.reply([{"text": self.final("Q1", question)}])
        with tempfile.TemporaryDirectory() as temporary, self.make_client(handle) as client:
            record, _ = execute_research(client, Settings(api_key="offline-only-key"), question, session=self.session(), directory=Path(temporary))
        self.assertEqual(record["status"], "answered")
        self.assertEqual(record["answer_repairs"], 1)
        self.assertEqual(record["tool_calls"], 0)
        self.assertEqual(record["model_calls"], 2)
        self.assertEqual(record["evidence"][0]["quote"], question)
        self.assertEqual(record["model_responses"][-1]["phase"], "answer_correction")

    def test_truncated_schema_response_is_rejected_with_no_extra_request(self):
        requests = []
        question = "The supplied count is seven. Return the count."
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assert_schema_without_tools(body)
            return self.reply([{"text": self.final("Q1", question)}], finish="MAX_TOKENS")
        with tempfile.TemporaryDirectory() as temporary, self.make_client(handle) as client:
            record, _ = execute_research(client, Settings(api_key="offline-only-key"), question, session=self.session(), directory=Path(temporary), max_model_calls=1)
        self.assertEqual(record["status"], "output_limit")
        self.assertEqual(record["answer"], "")
        self.assertEqual(len(requests), 1)
        self.assertEqual(record["tool_calls"], 0)

    def test_tool_limit_also_leaves_a_request_for_finalization(self):
        requests = []
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                return self.reply([{"functionCall": {"name": "multiply", "args": {"a": 2, "b": 3}}, "thoughtSignature": "c2ln"}])
            self.assert_schema_without_tools(body)
            return self.reply([{"text": json.dumps({"status": "unresolved", "answer": "", "evidence": [], "reason": "Example stopping response."})}])
        with self.make_client(handle) as client:
            result = run_agent(client, "test-model", "Use the supplied numbers.", max_model_calls=8, max_tool_calls=1, final_response_schema=FINAL_RESPONSE_SCHEMA, reserve_final_call=True)
        self.assertEqual((result.model_calls, result.tool_calls), (2, 1))
        self.assertEqual(result.model_events[-1]["phase"], "finalization")

    def test_timeout_category_is_saved_without_raw_exception_details_or_retry(self):
        calls = []
        def handle(request):
            calls.append(request)
            if len(calls) == 1:
                return self.reply([{"functionCall": {"name": "read_url", "args": {"url": URL}}, "thoughtSignature": "c2ln"}])
            raise httpx.ReadTimeout("PRIVATE_BODY_WITH_SECRET", request=request)
        with tempfile.TemporaryDirectory() as temporary, self.make_client(handle) as client:
            record, path = execute_research(client, Settings(api_key="offline-only-key"), "Read the original report.", session=self.session(), directory=Path(temporary))
            saved = path.read_text(encoding="utf-8")
        self.assertEqual(record["status"], "provider_error")
        self.assertEqual(record["provider_error_type"], "ReadTimeout")
        self.assertNotIn("PRIVATE_BODY_WITH_SECRET", saved)
        self.assertEqual(len(record["sources"]), 1)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
