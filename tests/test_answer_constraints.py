"""Exercise constraint failures with valid excerpts and recover within the existing budget."""

import json
from pathlib import Path
import tempfile
import unittest

from google import genai
from google.genai import types
import httpx

from traceagent.config import Settings
from traceagent.research import ResearchSession, execute_research


QUESTION = (
    "Who won the studio medal after 2015? Use only this archive.\n\n"
    "Lila won in 2012. Noah won in 2015. Mira won in 2018."
)


def candidate(name, quote):
    return json.dumps({
        "status": "answered",
        "answer": name,
        "evidence": [{"source_id": "Q1", "quote": quote}],
        "reason": "",
    })


class YearBoundTests(unittest.TestCase):
    def test_after_is_strict_and_requires_a_year_for_the_selected_name(self):
        session = ResearchSession()
        session.bind_question(QUESTION)
        for name, quote in (
            ("Lila", "Lila won in 2012."),
            ("Noah", "Noah won in 2015."),
            ("Lila", "Lila won in 2012. Noah won in 2015. Mira won in 2018."),
            ("Mira", "Noah won in 2015."),
        ):
            with self.subTest(name=name, quote=quote):
                verdict = session.verify_answer(candidate(name, quote))
                self.assertEqual(verdict["status"], "constraint_error")
                self.assertEqual(verdict["answer"], "")
        verdict = session.verify_answer(candidate("Mira", "Mira won in 2018."))
        self.assertEqual(verdict["status"], "answered")
        self.assertEqual(verdict["answer_constraint_check"], "passed")

    def test_before_is_strict_and_binding_a_new_question_resets_the_rule(self):
        session = ResearchSession()
        session.bind_question("Who won before 2015?\n\nArchive:\nLila won in 2012. Noah won in 2015.")
        self.assertEqual(
            session.verify_answer(candidate("Noah", "Noah won in 2015."))["status"],
            "constraint_error",
        )
        self.assertEqual(
            session.verify_answer(candidate("Lila", "Lila won in 2012."))["status"],
            "answered",
        )
        session.bind_question("How many were awarded after 2015? The ledger reports 12 awards.")
        verdict = session.verify_answer(candidate("12", "The ledger reports 12 awards."))
        self.assertEqual(verdict["status"], "answered")
        self.assertNotIn("answer_constraint_check", verdict)

    def test_ambiguous_cited_years_do_not_salvage_an_ineligible_candidate(self):
        session = ResearchSession()
        session.bind_question("Who won after 2015?\n\nArchive:\nMira won in 2012 and 2018.")
        result = session.verify_answer(candidate("Mira", "Mira won in 2012 and 2018."))
        self.assertEqual(result["status"], "constraint_error")


class YearBoundTransportTests(unittest.TestCase):
    def exercise(self, max_calls, repair_succeeds):
        requests = []
        archive = (
            "What is the first name of the designer who won the Cedar Prize (after 2015)?\n\n"
            "Archive:\nNico won in 2014.\nTari won in 2018."
        )
        session = ResearchSession()
        session.bind_question(archive)
        entries = session.question_source["excerpts"]

        def reply(name, year):
            excerpt = next(e for e in entries if name in e["text"] and year in e["text"] and len(e["text"].split()) <= 10)
            return json.dumps({
                "status": "answered", "answer": name, "reason": "",
                "evidence": [{"source_id": "Q1", "excerpt_id": excerpt["excerpt_id"]}],
            })

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if len(requests) == 1:
                self.assertIn("strictly after 2015", body["contents"][0]["parts"][0]["text"])
                result = reply("Nico", "2014")
            else:
                self.assertFalse(body.get("tools"))
                self.assertIn("The cited year 2014", body["contents"][-1]["parts"][0]["text"])
                result = reply("Tari", "2018")
            return httpx.Response(200, json={"candidates": [{
                "content": {"role": "model", "parts": [{"text": result}]},
                "finishReason": "STOP",
            }]})

        with tempfile.TemporaryDirectory() as temporary, genai.Client(
            api_key="offline-only-key", vertexai=False, http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1),
                client_args={"transport": httpx.MockTransport(handle), "trust_env": False},
            ),
        ) as client:
            record, _ = execute_research(
                client, Settings(api_key="offline-only-key"), archive, session=session,
                directory=Path(temporary), max_model_calls=max_calls,
            )
        self.assertEqual(len(requests), max_calls)
        self.assertEqual(record["evidence_check"], "passed")
        self.assertFalse(record["factual_entailment_checked"])
        self.assertEqual(record["validation_events"][0]["status"], "constraint_error")
        self.assertEqual(record["validation_events"][0]["repair_scheduled"], repair_succeeds)
        return record

    def test_failed_constraint_uses_existing_tool_free_correction(self):
        record = self.exercise(2, repair_succeeds=True)
        self.assertEqual(record["answer"], "Tari")
        self.assertEqual(record["answer_constraint_check"], "passed")
        self.assertEqual(record["answer_repairs"], 1)

    def test_final_request_with_no_remaining_budget_leaves_answer_empty(self):
        record = self.exercise(1, repair_succeeds=False)
        self.assertEqual(record["status"], "constraint_error")
        self.assertEqual(record["answer"], "")
        self.assertEqual(record["answer_constraint_check"], "failed")
        self.assertEqual(record["answer_repairs"], 0)


if __name__ == "__main__":
    unittest.main()
