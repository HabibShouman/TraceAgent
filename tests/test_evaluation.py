"""Evaluation checkpoints and actual HTTP request guards, with mocked transport."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from traceagent import evaluation as ev
from traceagent.budget import RequestBudgetExceeded
from traceagent.config import Settings


def questions():
    return [
        {"task_id": "task-a", "question": "Find the sample mass in the report.", "file_name": "", "answer": "DO_NOT_RETAIN_LABELS"},
        {"task_id": "task-b", "question": "Find the same laboratory measurement.", "file_name": ""},
        {"task_id": "task-c", "question": "Read the supplied recording.", "file_name": "recording.mp3"},
        {"task_id": "task-d", "question": "Watch https://www.youtube.com/watch?v=example and report the event.", "file_name": ""},
    ]


class SnapshotTests(unittest.TestCase):
    def test_controller_pilot_has_local_provenance_and_frozen_four_request_limit(self):
        def prepare_pilot(root):
            return ev.prepare_evaluation(Path(root) / "context-fixture", [{"task_id": "context-fixture", "question": "What is the supplied sample mass?", "file_name": ""}], max_model_calls=4, source_url="local:offline-context-fixture")

        with tempfile.TemporaryDirectory() as temporary, patch.object(ev, "fetch_course_questions", side_effect=AssertionError("No course request")):
            manifest = prepare_pilot(root=Path(temporary))
            self.assertEqual(manifest["source_url"], "local:offline-context-fixture")
            self.assertEqual(ev.evaluation_summary(manifest)["states"], {"pending": 1})
            self.assertEqual(manifest["profile"]["max_model_calls"], 4)
            self.assertEqual(manifest["profile"]["tool_availability_version"], 2)
            self.assertEqual(manifest["profile"]["search_policy"], "budget_only")
            self.assertEqual(manifest["profile"]["evidence_mode"], "registered_ids_or_exact_quote")
            self.assertEqual(manifest["profile"]["reading_context"], "retained_passages")
            self.assertEqual(ev.evaluation_summary(manifest)["requests_attempted"], 0)
            with self.assertRaises(ev.EvaluationError):
                prepare_pilot(root=Path(temporary))

    def test_historical_v7_helper_cannot_prepare_a_misnamed_new_profile(self):
        from examples.prepare_evidence_pilot import prepare_pilot

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ev.EvaluationError, "historical v7"):
                prepare_pilot(root=Path(temporary))
            self.assertFalse(any(Path(temporary).iterdir()))

    def test_historical_v5_helper_cannot_prepare_a_misnamed_new_profile(self):
        from examples.prepare_controller_pilot import prepare_pilot

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ev.EvaluationError, "historical v5"):
                prepare_pilot(root=Path(temporary))
            self.assertFalse(any(Path(temporary).iterdir()))

    def test_historical_v6_helper_cannot_prepare_a_misnamed_new_profile(self):
        from examples.prepare_controller_pilot_v6 import prepare_pilot

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ev.EvaluationError, "historical v6"):
                prepare_pilot(root=Path(temporary))
            self.assertFalse(any(Path(temporary).iterdir()))

    def test_snapshot_retains_every_task_excludes_labels_and_exports_coverage_not_score(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            manifest = ev.prepare_evaluation(directory, questions(), model="test-model")
            self.assertEqual(ev.evaluation_summary(manifest)["states"], {"pending": 2, "unsupported": 2})
            self.assertNotIn("DO_NOT_RETAIN_LABELS", (directory / "questions.json").read_text())
            with self.assertRaises(ev.EvaluationError):
                ev.prepare_evaluation(directory, questions(), model="other-model")
            answer_path, report_path = ev.export_evaluation(directory)
            answers = json.loads(answer_path.read_text())
            report = json.loads(report_path.read_text())
            self.assertEqual(len(answers), 4)
            self.assertTrue(all(item["submitted_answer"] == "" for item in answers))
            self.assertEqual(report["total_tasks"], 4)
            self.assertIsNone(report["official_score"])
            self.assertTrue(report["draft"])

    def test_snapshot_profile_and_implementation_changes_cannot_mix_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            manifest = ev.prepare_evaluation(directory, questions(), model="test-model")
            factory = Mock()
            with patch.object(ev, "implementation_fingerprint", return_value="changed"), self.assertRaises(ev.EvaluationError):
                ev.run_evaluation(directory, Settings(api_key="test-secret", model="test-model", search_backend="serper"), request_budget=8, client_factory=factory)
            factory.assert_not_called()
            modified = json.loads((directory / "questions.json").read_text())
            modified[0]["question"] = "A different task."
            ev.atomic_json(directory / "questions.json", modified)
            with self.assertRaises(ev.EvaluationError):
                ev.load_evaluation(directory)
            ev.atomic_json(directory / "questions.json", ev.normalize_questions(questions()))
            manifest["profile"]["model"] = "different-model"
            ev.atomic_json(directory / "manifest.json", manifest)
            with self.assertRaises(ev.EvaluationError):
                ev.load_evaluation(directory)

    def test_rejects_duplicate_ids_path_names_and_concurrent_writers(self):
        for name in ("../outside", "bad/name", "", "x" * 65):
            with self.subTest(name=name), self.assertRaises(ev.EvaluationError):
                ev.evaluation_path(name)
        duplicate = questions()[:1] * 2
        with self.assertRaises(ev.EvaluationError):
            ev.normalize_questions(duplicate)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            with ev.evaluation_lock(directory):
                with self.assertRaises(ev.EvaluationError):
                    with ev.evaluation_lock(directory):
                        pass
            with ev.evaluation_lock(directory):
                pass

    def test_offline_cli_actions_do_not_load_keys_or_create_a_model_client(self):
        from traceagent import __main__ as cli

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            with patch.object(ev, "evaluation_path", return_value=directory), patch.object(ev, "fetch_course_questions", return_value=questions()), patch.object(cli, "load_settings", side_effect=AssertionError("Do not load keys")), patch.object(cli, "create_client", side_effect=AssertionError("Do not create a client")), redirect_stdout(StringIO()):
                for action in ("prepare", "status", "export"):
                    self.assertEqual(cli.main(["eval", action, "--name", "baseline"]), 0)
            self.assertTrue((directory / "answers.json").exists())
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            cli.main(["research", "Question", "--request-budget", "1"])
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            cli.main(["eval", "run", "--model", "a-different-model"])


try:
    import httpx
    from google import genai
    from google.genai import types
    from traceagent.research import ResearchSession, execute_research
    from traceagent.web import Download
except ModuleNotFoundError:
    httpx = None


@unittest.skipIf(httpx is None, "Install SDK dependencies")
class EvaluationHTTPTests(unittest.TestCase):
    source_url = "https://example.org/report.txt"
    source_text = "The sample mass was exactly seven grams after the final drying procedure."

    def settings(self):
        return Settings(api_key="offline-test-key", model="test-model", search_backend="serper", serper_api_key="offline-search-key")

    def factory(self, directory, plan, requests):
        def handle(request):
            manifest, _ = ev.load_evaluation(directory)
            # The request reservation must be durable before HTTP transport runs.
            current = manifest["sessions"][-1]
            expected_current = len(requests) + 1 - sum(s["requests_attempted"] for s in manifest["sessions"][:-1])
            self.assertEqual(current["requests_attempted"], expected_current)
            requests.append(json.loads(request.content))
            status, parts = plan[len(requests) - 1]
            if status != 200:
                return httpx.Response(status, json={"error": {"code": status, "message": "PRIVATE_PROVIDER_BODY", "status": "RESOURCE_EXHAUSTED" if status == 429 else "UNAVAILABLE"}})
            return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]})

        def create(settings, timeout_ms, before_request):
            return genai.Client(api_key=settings.api_key, vertexai=False, http_options=types.HttpOptions(timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1), client_args={"transport": httpx.MockTransport(handle), "event_hooks": {"request": [before_request]}, "trust_env": False}))
        return create

    def plan(self):
        return [(200, [{"functionCall": {"name": "read_url", "args": {"url": self.source_url}, "id": "read-1"}, "thoughtSignature": "c2ln"}]), (200, [{"text": json.dumps({"status": "answered", "answer": "seven grams", "evidence": [{"source_id": "S1", "quote": self.source_text}]})}])]

    def runner(self, client, settings, question, **kwargs):
        session = ResearchSession(fetcher=Mock(return_value=Download(self.source_url, "text/plain", self.source_text.encode())), searcher=Mock(return_value=[]))
        return execute_research(client, settings, question, session=session, **kwargs)

    def test_complete_resume_skips_answers_and_export_preserves_full_denominator(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            ev.prepare_evaluation(directory, questions(), model="test-model", max_model_calls=2)
            requests = []
            factory = self.factory(directory, self.plan() * 2, requests)
            result = ev.run_evaluation(directory, self.settings(), request_budget=4, max_tasks=2, client_factory=factory, research_runner=self.runner)
            self.assertEqual([t["state"] for t in result["tasks"]], ["answered", "answered", "unsupported", "unsupported"])
            self.assertEqual(len(requests), 4)
            self.assertIn("only the requested final answer", requests[0]["contents"][0]["parts"][0]["text"])
            self.assertNotIn("task-a", json.dumps(requests[0]["contents"]))
            result = ev.run_evaluation(directory, self.settings(), request_budget=4, max_tasks=2, client_factory=factory, research_runner=self.runner)
            self.assertEqual(len(requests), 4)
            self.assertEqual(result["sessions"][-1]["requests_attempted"], 0)
            paths = ev.export_evaluation(directory)
            answers = json.loads(paths[0].read_text())
            self.assertEqual([x["submitted_answer"] for x in answers], ["seven grams", "seven grams", "", ""])
            self.assertIsNone(json.loads(paths[1].read_text())["official_score"])

    def test_cli_displays_finalization_and_task_result_with_mocked_transport(self):
        from traceagent import __main__ as cli

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            ev.prepare_evaluation(directory, questions(), model="test-model", max_model_calls=2)
            requests = []
            output = StringIO()
            with patch.object(ev, "evaluation_path", return_value=directory), patch.object(cli, "load_settings", return_value=self.settings()), patch.object(cli, "create_client", side_effect=self.factory(directory, self.plan(), requests)):
                # Exercise the actual graph with local report observations.
                with patch("traceagent.research.ResearchSession", side_effect=lambda **kwargs: ResearchSession(fetcher=Mock(return_value=Download(self.source_url, "text/plain", self.source_text.encode())), searcher=Mock(return_value=[]))), redirect_stdout(output):
                    self.assertEqual(cli.main(["eval", "run", "--name", "baseline", "--request-budget", "2", "--max-tasks", "1", "--diagnose"]), 0)
            self.assertIn("finalizing: using existing evidence", output.getvalue())
            self.assertIn("result: answered", output.getvalue())
            self.assertEqual(len(requests), 2)

    def test_result_callback_observes_a_durable_task_checkpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            ev.prepare_evaluation(directory, questions(), model="test-model", max_model_calls=2)
            seen = []
            def completed(record):
                saved, _ = ev.load_evaluation(directory)
                self.assertEqual(saved["tasks"][0]["state"], "answered")
                self.assertEqual(saved["tasks"][0]["attempts"][-1]["status"], record["status"])
                seen.append(record["status"])
            requests = []
            ev.run_evaluation(directory, self.settings(), request_budget=2, client_factory=self.factory(directory, self.plan(), requests), research_runner=self.runner, on_result=completed)
            self.assertEqual(seen, ["answered"])

    def test_quota_and_service_errors_stop_queue_and_preserve_completed_answers(self):
        for status, reason in ((429, "provider_quota"), (503, "provider_error")):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary) / "baseline"
                ev.prepare_evaluation(directory, questions(), model="test-model", max_model_calls=2)
                requests = []
                factory = self.factory(directory, self.plan() + [(status, [])] + self.plan(), requests)
                result = ev.run_evaluation(directory, self.settings(), request_budget=4, max_tasks=2, client_factory=factory, research_runner=self.runner)
                self.assertEqual([t["state"] for t in result["tasks"]][:2], ["answered", "retryable_error"])
                self.assertEqual(result["sessions"][-1]["stop_reason"], reason)
                self.assertEqual(result["sessions"][-1]["requests_attempted"], 3)
                self.assertEqual(len(requests), 3)
                self.assertNotIn("PRIVATE_PROVIDER_BODY", (directory / "manifest.json").read_text())
                result = ev.run_evaluation(directory, self.settings(), request_budget=2, client_factory=factory, research_runner=self.runner)
                self.assertEqual(len(requests), 5)
                self.assertEqual(len(result["tasks"][0]["attempts"]), 1)
                self.assertEqual(len(result["tasks"][1]["attempts"]), 2)
                self.assertEqual(result["tasks"][1]["state"], "answered")
                self.assertEqual(ev.evaluation_summary(result)["requests_attempted"], 5)

    def test_insufficient_reserved_budget_does_not_start_a_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            ev.prepare_evaluation(directory, questions(), model="test-model", max_model_calls=2)
            requests = []
            result = ev.run_evaluation(directory, self.settings(), request_budget=1, client_factory=self.factory(directory, [], requests), research_runner=self.runner)
            self.assertEqual(result["sessions"][-1]["stop_reason"], "request_budget_reserved")
            self.assertEqual(result["tasks"][0]["state"], "pending")
            self.assertEqual(requests, [])

    def test_http_guard_blocks_excess_request_before_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            manifest = ev.prepare_evaluation(directory, questions(), model="test-model")
            session = {"state": "running", "request_budget": 2, "requests_attempted": 0}
            manifest["sessions"].append(session)
            budget = ev.SessionBudget(directory, manifest, session)
            budget.attempt = {"requests_attempted": 0}
            requests = []
            factory = self.factory(directory, [(200, [{"text": "ok"}])] * 2, requests)
            with factory(self.settings(), 90_000, budget.before_request) as client:
                for _ in range(2):
                    client.models.generate_content(model="test-model", contents="test", config=types.GenerateContentConfig(automatic_continuation=False))
                with self.assertRaises(RequestBudgetExceeded):
                    client.models.generate_content(model="test-model", contents="test", config=types.GenerateContentConfig(automatic_continuation=False))
            self.assertEqual(len(requests), 2)
            self.assertEqual(ev.load_evaluation(directory)[0]["sessions"][-1]["requests_attempted"], 2)

    def test_interruption_preserves_attempted_requests_and_can_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "baseline"
            ev.prepare_evaluation(directory, questions(), model="test-model", max_model_calls=2)
            requests = []
            factory = self.factory(directory, [(200, [{"text": "before interruption"}])] + self.plan(), requests)
            def interrupt(client, settings, question, **kwargs):
                client.models.generate_content(model="test-model", contents=question, config=types.GenerateContentConfig(automatic_continuation=False))
                raise KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                ev.run_evaluation(directory, self.settings(), request_budget=2, client_factory=factory, research_runner=interrupt)
            saved, _ = ev.load_evaluation(directory)
            self.assertEqual(saved["tasks"][0]["state"], "retryable_error")
            self.assertEqual(saved["tasks"][0]["attempts"][0]["requests_attempted"], 1)
            # Simulate an abrupt process exit, which cannot execute finally.
            saved["sessions"][-1]["state"] = "running"
            saved["tasks"][0]["state"] = "running"
            saved["tasks"][0]["attempts"][-1]["status"] = "running"
            ev.atomic_json(directory / "manifest.json", saved)
            resumed = ev.run_evaluation(directory, self.settings(), request_budget=2, client_factory=factory, research_runner=self.runner)
            self.assertEqual(resumed["tasks"][0]["state"], "answered")
            self.assertEqual(len(resumed["tasks"][0]["attempts"]), 2)
            self.assertEqual(ev.evaluation_summary(resumed)["requests_attempted"], 3)
            self.assertEqual(resumed["sessions"][0]["state"], "interrupted")

    def test_course_fetch_is_read_only_and_rejects_unexpected_task_count(self):
        payload = [{"task_id": f"task-{index}", "question": "A public question.", "file_name": ""} for index in range(20)]
        def handle(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(str(request.url), ev.QUESTIONS_URL)
            return httpx.Response(200, json=payload)
        client = httpx.Client(transport=httpx.MockTransport(handle), trust_env=False)
        with patch("httpx.Client", return_value=client):
            self.assertEqual(len(ev.fetch_course_questions()), 20)
        client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload[:1])), trust_env=False)
        with patch("httpx.Client", return_value=client), self.assertRaises(ev.EvaluationError):
            ev.fetch_course_questions()


if __name__ == "__main__":
    unittest.main()
