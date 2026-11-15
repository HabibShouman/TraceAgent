"""Exercise graph routing and tool boundaries with scripted model responses."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from traceagent.tools import multiply

try:
    from google.genai import types
    from traceagent.agent import run_agent
except ModuleNotFoundError as error:
    if (error.name or "").split(".")[0] not in {"google", "langgraph"}:
        raise
    types = None


def response(*parts, tokens=10):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=3, total_token_count=tokens,
        ),
    )


def scripted_client(*responses):
    return SimpleNamespace(
        vertexai=False,
        _api_client=SimpleNamespace(vertexai=False),
        models=SimpleNamespace(generate_content=Mock(side_effect=responses)),
    )


@unittest.skipIf(types is None, "Install project dependencies to exercise the graph.")
class AgentTests(unittest.TestCase):
    def test_tool_result_returns_to_model_and_preserves_signature_and_call_id(self):
        requested = types.Part(
            function_call=types.FunctionCall(name="multiply", args={"a": 17, "b": 23}, id="c1"),
            thought_signature=b"test-signature",
        )
        client = scripted_client(response(requested), response(types.Part(text="391")))
        result = run_agent(client, "test-model", "Compute 17 times 23.")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.answer, "391")
        self.assertEqual((result.model_calls, result.tool_calls), (2, 1))
        self.assertEqual((result.input_tokens, result.total_tokens), (6, 20))
        followup = client.models.generate_content.call_args_list[1].kwargs["contents"]
        self.assertEqual(followup[1].parts[0].thought_signature, b"test-signature")
        returned = followup[2].parts[0].function_response
        self.assertEqual(returned.id, "c1")
        self.assertEqual(returned.response, {"result": 391.0})
        config = client.models.generate_content.call_args_list[0].kwargs["config"]
        self.assertTrue(config.automatic_function_calling.disable)

    def test_model_may_finish_without_a_tool_and_thought_text_is_not_the_answer(self):
        client = scripted_client(response(
            types.Part(text="private internal text", thought=True),
            types.Part(text="Hello"),
        ))
        result = run_agent(client, "test-model", "Say hello.")
        self.assertEqual(result.answer, "Hello")
        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(result.events, [])

    def test_repeated_tool_requests_stop_at_model_call_limit(self):
        call = response(types.Part(function_call=types.FunctionCall(
            name="multiply", args={"a": 2, "b": 3},
        )))
        client = scripted_client(call, call, call)
        result = run_agent(client, "test-model", "Multiply.", max_model_calls=3)
        self.assertEqual(result.status, "limit_reached")
        self.assertEqual(result.answer, "")
        self.assertEqual((result.model_calls, result.tool_calls), (3, 2))

    def test_batch_over_tool_limit_is_not_executed(self):
        part = types.Part(function_call=types.FunctionCall(name="multiply", args={"a": 2, "b": 3}))
        client = scripted_client(response(part, part))
        result = run_agent(client, "test-model", "Multiply twice.", max_tool_calls=1)
        self.assertEqual(result.status, "limit_reached")
        self.assertEqual(result.tool_calls, 0)

    def test_invalid_and_unknown_calls_return_errors_instead_of_running_arbitrary_code(self):
        client = scripted_client(
            response(
                types.Part(function_call=types.FunctionCall(name="multiply", args={"a": 2})),
                types.Part(function_call=types.FunctionCall(name="not_a_tool", args={})),
            ),
            response(types.Part(text="The tool calls failed.")),
        )
        result = run_agent(client, "test-model", "Try the tools.")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.tool_calls, 2)
        self.assertTrue(all("error" in event for event in result.events))

    def test_empty_response_does_not_claim_completion(self):
        client = scripted_client(types.GenerateContentResponse())
        result = run_agent(client, "test-model", "Hello")
        self.assertEqual(result.status, "empty_response")
        self.assertEqual(result.answer, "")

    def test_rejects_empty_question_before_network_access(self):
        client = scripted_client()
        with self.assertRaises(ValueError):
            run_agent(client, "test-model", " ")
        client.models.generate_content.assert_not_called()


class ArithmeticBoundaryTests(unittest.TestCase):
    def test_rejects_non_numeric_and_non_finite_inputs_and_overflow(self):
        for a, b in (("2", 3), (True, 3), (float("nan"), 2), (float("inf"), 2), (1e308, 1e308)):
            with self.subTest(a=a, b=b), self.assertRaises((ValueError, OverflowError)):
                multiply(a, b)


if __name__ == "__main__":
    unittest.main()
