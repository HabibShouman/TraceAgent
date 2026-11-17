"""Keep benchmark solutions out of observations and retain invalidated history."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from traceagent import evaluation as ev
from traceagent.config import Settings
from traceagent.research import ResearchSession, execute_research
from traceagent.tools import ToolError
from traceagent.web import Download


LABEL_CANARY = "WITHHELD_LABEL_CANARY"
PUBLIC_URL = "https://example.org/original-report"
EXCLUDED_URL = "https://huggingface.co/datasets/example/evaluation-data"
TASK_ID = "01234567-1234-1234-1234-0123456789ab"


class SourceBoundaryTests(unittest.TestCase):
    def test_search_omits_excluded_urls_and_answer_bearing_snippets(self):
        results = [
            {"href": EXCLUDED_URL, "title": "Data", "body": LABEL_CANARY},
            {"href": "https://example.org/blog", "title": "GAIA solutions", "body": LABEL_CANARY},
            {"href": "https://example.org/rows", "title": "Table", "body": "task_id question final_answer " + LABEL_CANARY},
            {"href": PUBLIC_URL, "title": "Original report", "body": "A primary factual source."},
        ]
        session = ResearchSession(searcher=Mock(return_value=results), benchmark_mode=True)
        observed = session.search_web("original report")
        self.assertEqual([item["url"] for item in observed["results"]], [PUBLIC_URL])
        self.assertNotIn(LABEL_CANARY, json.dumps(observed))
        self.assertNotIn(LABEL_CANARY, json.dumps(session.blocked_material))
        self.assertEqual(len(session.blocked_material), 3)

    def test_solution_and_task_id_queries_stop_before_search_provider(self):
        for query in ("GAIA answers", "agents-course unit4 solutions", TASK_ID):
            with self.subTest(query=query):
                searcher = Mock()
                session = ResearchSession(searcher=searcher, benchmark_mode=True)
                with self.assertRaises(ToolError) as caught:
                    session.search_web(query)
                self.assertEqual(caught.exception.code, "benchmark_material")
                searcher.assert_not_called()
                self.assertEqual(session.search_requests, 0)

    def test_excluded_url_stops_before_download_and_redirect_stops_before_parse(self):
        fetcher, parser = Mock(), Mock()
        session = ResearchSession(fetcher=fetcher, parser=parser, benchmark_mode=True)
        with self.assertRaises(ToolError):
            session.read_url(EXCLUDED_URL)
        fetcher.assert_not_called()
        fetcher.return_value = Download(EXCLUDED_URL, "text/plain", LABEL_CANARY.encode())
        with self.assertRaises(ToolError):
            session.read_url(PUBLIC_URL)
        parser.assert_not_called()
        self.assertEqual(session.sources, {})
        self.assertEqual(session.documents, {})

    def test_answer_table_is_rejected_before_passages_or_cache_can_expose_it(self):
        document = {"title": "Report", "kind": "text", "links": [], "pages": [
            {"page": None, "text": "An ordinary introduction."},
            {"page": None, "text": "task_id | question | final_answer\n" + TASK_ID + " | example | " + LABEL_CANARY},
        ]}
        session = ResearchSession(fetcher=Mock(return_value=Download(PUBLIC_URL, "text/plain", b"unused")), parser=Mock(return_value=document), benchmark_mode=True)
        with self.assertRaises(ToolError) as caught:
            session.read_url(PUBLIC_URL, focus="ordinary introduction")
        self.assertEqual(caught.exception.code, "benchmark_material")
        self.assertNotIn(LABEL_CANARY, str(caught.exception))
        self.assertEqual(session.sources, {})
        self.assertEqual(session.documents, {})
        self.assertEqual(session.read_cache, {})

    def test_solution_link_labels_are_filtered_but_ordinary_sources_remain(self):
        document = {"title": "Report", "kind": "text", "pages": [{"page": None, "text": "An independent original report."}], "links": [
            {"url": "https://example.org/blog", "title": "GAIA answers " + LABEL_CANARY},
            {"url": EXCLUDED_URL, "title": LABEL_CANARY},
            {"url": "https://example.org/paper.pdf", "title": "Paper"},
        ]}
        session = ResearchSession(fetcher=Mock(return_value=Download(PUBLIC_URL, "text/plain", b"unused")), parser=Mock(return_value=document), benchmark_mode=True)
        observed = session.read_url(PUBLIC_URL)
        self.assertNotIn(LABEL_CANARY, json.dumps(observed))
        self.assertEqual(len(observed["links"]), 1)
        self.assertEqual(observed["source_id"], "S1")

    def test_non_benchmark_research_can_read_legitimate_dataset_documentation(self):
        session = ResearchSession(fetcher=Mock(return_value=Download(EXCLUDED_URL, "text/plain", b"This dataset documents its measurement methods.")))
        self.assertEqual(session.read_url(EXCLUDED_URL)["source_id"], "S1")

    def test_question_evidence_is_explicit_and_cannot_invent_input_text(self):
        question = "Convert the supplied word 'river' to uppercase."
        session = ResearchSession(fetcher=Mock(), searcher=Mock())
        session.bind_question(question)
        final = {"status": "answered", "answer": "RIVER", "evidence": [{"source_id": "Q1", "quote": question}]}
        verified = session.verify_answer(json.dumps(final))
        self.assertEqual(verified["status"], "answered")
        self.assertEqual(verified["evidence"][0]["kind"], "question")
        self.assertEqual(verified["evidence"][0]["url"], "input:question")
        final["evidence"][0]["quote"] = "A fabricated input that was never supplied."
        self.assertEqual(session.verify_answer(json.dumps(final))["status"], "evidence_error")
        session.fetcher.assert_not_called()
        session.searcher.assert_not_called()


class AuditHistoryTests(unittest.TestCase):
    def test_invalidated_evaluation_preserves_attempts_blocks_run_and_withholds_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "history"
            manifest = ev.prepare_evaluation(directory, [{"task_id": "example-task", "question": "A self-contained sample question.", "file_name": ""}], model="test-model")
            manifest["tasks"][0].update(state="answered", submitted_answer="original candidate", attempts=[{"status": "answered", "requests_attempted": 2}])
            ev.atomic_json(directory / "manifest.json", manifest)
            snapshot_before = (directory / "questions.json").read_bytes()
            ev.invalidate_evaluation(directory, "A source contained benchmark answer labels.", task_id="example-task")
            saved, _ = ev.load_evaluation(directory)
            self.assertEqual(saved["tasks"], manifest["tasks"])
            self.assertEqual((directory / "questions.json").read_bytes(), snapshot_before)
            factory = Mock()
            with self.assertRaisesRegex(ev.EvaluationError, "invalidated"):
                ev.run_evaluation(directory, Settings(api_key="unused", model="test-model"), request_budget=8, client_factory=factory)
            factory.assert_not_called()
            answers, report = ev.export_evaluation(directory)
            self.assertEqual(json.loads(answers.read_text())[0]["submitted_answer"], "")
            audit = json.loads(report.read_text())
            self.assertEqual(audit["integrity_status"], "invalidated")
            self.assertEqual(audit["answers_prepared"], 1)
            self.assertEqual(audit["exportable_answers"], 0)
            self.assertTrue(audit["draft"])
            self.assertIsNone(audit["official_score"])


try:
    from google.genai import types
    from traceagent.agent import run_agent
except ModuleNotFoundError:
    types = None


@unittest.skipIf(types is None, "Install SDK/graph dependencies")
class InputReasoningTests(unittest.TestCase):
    def test_self_contained_answer_needs_one_model_call_and_no_external_evidence(self):
        question = "Convert the supplied word 'river' to uppercase."
        final = json.dumps({"status": "answered", "answer": "RIVER", "evidence": [{"source_id": "Q1", "quote": question}]})
        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(return_value=types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=final)]), finish_reason="STOP")]))))
        session = ResearchSession(fetcher=Mock(), searcher=Mock())
        with tempfile.TemporaryDirectory() as temporary:
            record, path = execute_research(client, Settings(api_key="offline-key"), "Formatting instructions.\n" + question, session=session, directory=Path(temporary), benchmark_mode=True, question_source=question)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "answered")
        self.assertEqual(record["model_calls"], 1)
        self.assertEqual(record["tool_calls"], 0)
        self.assertEqual(record["sources"], [])
        self.assertTrue(record["benchmark_mode"])
        self.assertEqual(saved["question_source"]["passages"][0]["text"], question)
        self.assertFalse(record["factual_entailment_checked"])
        session.fetcher.assert_not_called()
        session.searcher.assert_not_called()

    def test_withheld_labels_never_enter_followup_model_observations_or_saved_record(self):
        def response(part):
            return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[part]), finish_reason="STOP")])

        client = SimpleNamespace(vertexai=False, models=SimpleNamespace(generate_content=Mock(side_effect=[
            response(types.Part(function_call=types.FunctionCall(name="search_web", args={"query": "original report"}))),
            response(types.Part(function_call=types.FunctionCall(name="read_url", args={"url": PUBLIC_URL}))),
            response(types.Part(text='{"status":"unresolved","reason":"No independent evidence."}')),
        ])))
        session = ResearchSession(
            searcher=Mock(return_value=[{"href": EXCLUDED_URL, "title": "Dataset", "body": LABEL_CANARY}]),
            fetcher=Mock(return_value=Download(PUBLIC_URL, "text/plain", ("task_id question final_answer " + LABEL_CANARY).encode())),
        )
        with tempfile.TemporaryDirectory() as temporary:
            record, path = execute_research(client, Settings(api_key="offline-key"), "Find a measurement in an original report.", session=session, directory=Path(temporary), benchmark_mode=True)
            self.assertNotIn(LABEL_CANARY, path.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "unresolved")
        self.assertEqual(record["sources"], [])
        self.assertEqual(len(record["blocked_material"]), 2)
        for call in client.models.generate_content.call_args_list:
            observations = " ".join(content.model_dump_json() for content in call.kwargs["contents"])
            self.assertNotIn(LABEL_CANARY, observations)


if __name__ == "__main__":
    unittest.main()
