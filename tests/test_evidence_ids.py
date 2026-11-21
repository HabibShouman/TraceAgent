"""Citations resolve to registered source spans, not model-written quotations."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from traceagent.config import Settings
from traceagent.evidence import EXCERPT_WORDS, MAX_EXCERPTS, MAX_EXCERPT_CHARS, excerpt_catalog
from traceagent.research import FINAL_RESPONSE_SCHEMA, ResearchSession, execute_research, normalized
from traceagent.web import Download

try:
    import httpx
    from google import genai
    from google.genai import types
except ModuleNotFoundError:
    httpx = None


URL = "https://example.org/calibration-report.txt"
TEXT = "The calibration sample contains seven grams of copper. The instrument was checked before each measurement."


def answer(*evidence):
    return json.dumps({"status": "answered", "answer": "seven grams", "evidence": list(evidence), "reason": ""})


def session(text=TEXT):
    return ResearchSession(fetcher=Mock(return_value=Download(URL, "text/plain", text.encode())))


class ExcerptTests(unittest.TestCase):
    def test_catalog_is_bounded_exact_and_prefers_the_focused_page(self):
        source = {"source_id": "S1", "kind": "pdf", "passages": [
            {"page": 1, "text": " ".join(f"unrelated{i}" for i in range(600))},
            {"page": 2, "text": TEXT},
        ]}
        excerpts = excerpt_catalog(source, "calibration")
        self.assertTrue(any(x["page"] == 2 for x in excerpts))
        self.assertEqual(excerpts[0]["page"], 2)
        self.assertLessEqual(len(excerpts), MAX_EXCERPTS)
        for x in excerpts:
            self.assertLessEqual(len(x["text"].split()), EXCERPT_WORDS)
            self.assertLessEqual(len(x["text"]), MAX_EXCERPT_CHARS)
            self.assertTrue(any(x["text"] in normalized(p["text"]) and x["page"] == p["page"] for p in source["passages"]))
        source["passages"] = [{"page": 1, "text": "x" * 2000}]
        self.assertEqual(excerpt_catalog(source), [])

    def test_registered_id_renders_exact_text_and_keeps_source_record(self):
        s = session(); source = s.read_url(URL, focus="calibration")
        excerpt = source["excerpts"][0]
        result = s.verify_answer(answer({"source_id": "S1", "excerpt_id": excerpt["excerpt_id"]}))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["evidence"][0]["quote"], excerpt["text"])
        self.assertEqual(result["evidence"][0]["excerpt_id"], excerpt["excerpt_id"])
        self.assertIn(TEXT, source["passages"][0]["text"])

    def test_compact_observation_keeps_outgoing_document_links(self):
        s = session(); source = s.read_url(URL)
        source["links"] = [{"title": f"Related document {i}", "url": f"https://example.org/document-{i}.pdf"} for i in range(25)]
        observation = s.model_observation("read_url", {"result": source})["result"]
        self.assertEqual(observation["links"], source["links"])
        self.assertNotIn("passages", observation)
        self.assertIn("passages", source)

    def test_unknown_wrong_source_and_ambiguous_ids_are_rejected(self):
        s = session(); first = s.read_url(URL); second = s.read_url(URL, focus="copper")
        for entry in (
            {"source_id": "S1", "excerpt_id": "S1-E999"},
            {"source_id": "S1", "excerpt_id": second["excerpts"][0]["excerpt_id"]},
            {"source_id": "S1", "excerpt_id": first["excerpts"][0]["excerpt_id"], "quote": "rewritten claim"},
            {"source_id": "S99", "excerpt_id": first["excerpts"][0]["excerpt_id"]},
        ):
            with self.subTest(entry=entry):
                self.assertEqual(s.verify_answer(answer(entry))["status"], "evidence_error")

    def test_catalog_text_cannot_bypass_membership_validation(self):
        s = session(); source = s.read_url(URL); excerpt = source["excerpts"][0]
        excerpt["text"] = "An invented observation absent from the source."
        result = s.verify_answer(answer({"source_id": "S1", "excerpt_id": excerpt["excerpt_id"]}))
        self.assertEqual(result["status"], "evidence_error")

    def test_word_limit_still_aggregates_across_ids_for_the_same_url(self):
        s = session(" ".join(f"token{i}" for i in range(80)))
        first = s.read_url(URL); second = s.read_url(URL, focus="token")
        refs = [{"source_id": "S1", "excerpt_id": first["excerpts"][0]["excerpt_id"]},
                {"source_id": "S2", "excerpt_id": second["excerpts"][0]["excerpt_id"]},
                {"source_id": "S2", "excerpt_id": second["excerpts"][1]["excerpt_id"]}]
        self.assertEqual(s.verify_answer(answer(*refs[:2]))["status"], "answered")
        self.assertEqual(s.verify_answer(answer(*refs))["status"], "evidence_error")

    def test_repeated_pdf_text_keeps_the_selected_registered_page(self):
        s = session(); s.parser = Mock(return_value={"title": "Calibration report", "kind": "pdf", "links": [], "pages": [{"page": 3, "text": TEXT}, {"page": 7, "text": TEXT}], "truncated": False})
        source = s.read_url(URL)
        excerpt = next(x for x in source["excerpts"] if x["page"] == 7)
        result = s.verify_answer(answer({"source_id": "S1", "excerpt_id": excerpt["excerpt_id"]}))
        self.assertEqual(result["evidence"][0]["page"], 7)

    def test_literal_ellipsis_remains_invalid_and_short_question_ids_are_supported(self):
        s = session(); s.read_url(URL)
        self.assertEqual(s.verify_answer(answer({"source_id": "S1", "quote": "The calibration sample...before each measurement."}))["status"], "evidence_error")
        s.bind_question("42")
        result = s.verify_answer(answer({"source_id": "Q1", "excerpt_id": "Q1-E1"}))
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["evidence"][0]["kind"], "question")
        self.assertEqual(s.question_source["passages"][0]["text"], "42")


@unittest.skipIf(httpx is None, "Install SDK dependencies")
class ExcerptTransportTests(unittest.TestCase):
    def client(self, handle):
        return genai.Client(api_key="offline-only-key", vertexai=False, http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
            client_args={"transport": httpx.MockTransport(handle), "trust_env": False},
        ))

    def reply(self, parts):
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]})

    def run_case(self, correction=False):
        requests = []; s = session()
        def handle(request):
            body = json.loads(request.content); requests.append(body)
            if len(requests) == 1:
                self.assertIn("Q1-E1", body["contents"][0]["parts"][0]["text"])
                return self.reply([{"functionCall": {"name": "read_url", "args": {"url": URL}, "id": "read-1"}, "thoughtSignature": "c2ln"}])
            observed = body["contents"][2]["parts"][0]["functionResponse"]
            self.assertEqual(observed["id"], "read-1")
            self.assertEqual(body["contents"][1]["parts"][0]["thoughtSignature"], "c2ln")
            result = observed["response"]["result"]
            self.assertNotIn("passages", result)
            self.assertLessEqual(len(result["excerpts"]), MAX_EXCERPTS)
            if correction and len(requests) == 2:
                return self.reply([{"text": answer({"source_id": "S1", "excerpt_id": "S1-E999"})}])
            if correction:
                self.assertFalse(body.get("tools"))
                self.assertEqual(body["generationConfig"]["responseJsonSchema"], FINAL_RESPONSE_SCHEMA)
                required = FINAL_RESPONSE_SCHEMA["properties"]["evidence"]["items"]["required"]
                self.assertIn("excerpt_id", required)
            return self.reply([{"text": answer({"source_id": "S1", "excerpt_id": result["excerpts"][0]["excerpt_id"]})}])
        with tempfile.TemporaryDirectory() as temporary, self.client(handle) as client:
            record, _ = execute_research(client, Settings(api_key="offline-only-key"), "Read the calibration report and return its sample mass.", session=s, directory=Path(temporary), max_model_calls=4)
        self.assertEqual(record["status"], "answered")
        self.assertEqual(record["evidence"][0]["quote"], s.sources["S1"]["excerpts"][0]["text"])
        self.assertIn("passages", record["sources"][0])
        self.assertFalse(record["factual_entailment_checked"])
        self.assertEqual(len(requests), 3 if correction else 2)
        self.assertEqual(record["answer_repairs"], int(correction))

    def test_model_selects_ids_and_program_renders_source_text(self):
        self.run_case()

    def test_unknown_id_can_be_corrected_with_schema_and_no_new_tools(self):
        self.run_case(correction=True)


if __name__ == "__main__":
    unittest.main()
