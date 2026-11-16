"""Exercise graph routing and tool boundaries with scripted model responses."""

from types import SimpleNamespace
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import Mock, patch

from traceagent.tools import multiply

try:
    from google.genai import types
    from traceagent.agent import AgentRequestError, run_agent
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
    def test_dependent_tools_use_the_observed_result_and_both_are_registered(self):
        client = scripted_client(
            response(types.Part(function_call=types.FunctionCall(
                name="multiply", args={"a": 17, "b": 23}, id="multiply-1",
            ))),
            response(types.Part(function_call=types.FunctionCall(
                name="add", args={"a": 391, "b": 8}, id="add-1",
            ))),
            response(types.Part(text="399")),
        )
        result = run_agent(client, "test-model", "Multiply 17 by 23, then add 8 to the result.")
        self.assertEqual(result.status, "complete")
        self.assertEqual(result.answer, "399")
        self.assertEqual((result.model_calls, result.tool_calls), (3, 2))
        self.assertEqual([event["tool"] for event in result.events], ["multiply", "add"])
        self.assertEqual([event["result"] for event in result.events], [391.0, 399.0])
        first_config = client.models.generate_content.call_args_list[0].kwargs["config"]
        names = {declaration.name for declaration in first_config.tools[0].function_declarations}
        self.assertEqual(names, {"multiply", "add"})
        contents = client.models.generate_content.call_args_list[2].kwargs["contents"]
        self.assertEqual(contents[2].parts[0].function_response.response, {"result": 391.0})
        self.assertEqual(contents[4].parts[0].function_response.response, {"result": 399.0})

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
        self.assertEqual([message.role for message in followup], ["user", "model", "user"])
        self.assertEqual(followup[1].parts[0].thought_signature, b"test-signature")
        returned = followup[2].parts[0].function_response
        self.assertEqual(returned.id, "c1")
        self.assertEqual(returned.response, {"result": 391.0})
        config = client.models.generate_content.call_args_list[0].kwargs["config"]
        self.assertTrue(config.automatic_function_calling.disable)
        declaration = config.tools[0].function_declarations[0]
        self.assertIsNone(declaration.response)
        self.assertIsNone(declaration.response_json_schema)
        self.assertEqual(set(declaration.parameters_json_schema["required"]), {"a", "b"})

    def test_sdk_sends_valid_roles_and_matching_function_response_over_transport(self):
        import json
        import httpx
        from google import genai

        requests = []

        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingLevel"], "LOW")
            self.assertEqual(body["generationConfig"]["maxOutputTokens"], 4096)
            if len(requests) == 1:
                parts = [{
                    "functionCall": {"name": "multiply", "args": {"a": 17, "b": 23}, "id": "multiply-1"},
                    "thoughtSignature": "dGVzdC1zaWduYXR1cmU=",
                }]
            else:
                self.assertEqual([content["role"] for content in body["contents"]], ["user", "model", "user"])
                function_response = body["contents"][2]["parts"][0]["functionResponse"]
                self.assertEqual(function_response["name"], "multiply")
                self.assertEqual(function_response["id"], "multiply-1")
                self.assertEqual(function_response["response"], {"result": 391.0})
                self.assertEqual(body["contents"][1]["parts"][0]["thoughtSignature"], "dGVzdC1zaWduYXR1cmU=")
                parts = [{"text": "391"}]
            return httpx.Response(200, json={
                "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
            })

        options = types.HttpOptions(
            client_args={"transport": httpx.MockTransport(handle)},
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        with genai.Client(api_key="offline-test-key", vertexai=False, http_options=options) as client:
            result = run_agent(client, "gemini-3.6-flash", "What is 17 times 23?", max_output_tokens=4096, thinking_level="low")
        self.assertEqual(result.answer, "391")
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(requests), 2)

    def test_failed_followup_preserves_completed_tool_context(self):
        provider_error = RuntimeError("sensitive provider body")
        client = scripted_client(
            response(types.Part(function_call=types.FunctionCall(
                name="multiply", args={"a": 17, "b": 23},
            ))),
            provider_error,
        )
        with self.assertRaises(AgentRequestError) as caught:
            run_agent(client, "test-model", "Compute 17 times 23.")
        failure = caught.exception
        self.assertEqual((failure.request_number, failure.tool_calls), (2, 1))
        self.assertEqual(failure.events[0]["result"], 391.0)
        self.assertIs(failure.provider_error, provider_error)
        self.assertEqual(len(failure.model_events), 1)
        self.assertEqual(failure.model_events[0]["request_number"], 1)
        self.assertNotIn("sensitive provider body", str(failure))

    def test_agent_cli_reports_request_number_and_redacted_validation_message(self):
        from traceagent.__main__ import agent_command
        from traceagent.config import Settings

        provider_error = RuntimeError("raw-body-secret")
        provider_error.code = 400
        provider_error.message = "Invalid tool schema, key=test-secret"
        failure = AgentRequestError(provider_error, 1, 0, [])
        output = StringIO()
        with patch("traceagent.agent.run_agent", side_effect=failure), \
             redirect_stderr(output), redirect_stdout(output):
            self.assertEqual(agent_command(object(), Settings(api_key="test-secret"), "Multiply.", diagnostic=True), 1)
        self.assertIn("model request 1", output.getvalue())
        self.assertIn("HTTP 400", output.getvalue())
        self.assertIn("Invalid tool schema", output.getvalue())
        self.assertNotIn("test-secret", output.getvalue())
        self.assertNotIn("raw-body-secret", output.getvalue())

    def test_model_may_finish_without_a_tool_and_thought_text_is_not_the_answer(self):
        client = scripted_client(response(
            types.Part(text="private internal text", thought=True),
            types.Part(text="Hello"),
        ))
        result = run_agent(client, "test-model", "Say hello.")
        self.assertEqual(result.answer, "Hello")
        self.assertEqual(result.tool_calls, 0)
        self.assertEqual(result.events, [])

    def test_token_limit_never_accepts_partial_text_or_executes_cut_off_tools(self):
        partial = '{"status":"answered","answer":"21","evidence":[{'
        cases = [
            [types.Part(text=partial)],
            [types.Part(text='{"status":"answered","answer":"21","evidence":[]}')],
            [types.Part(function_call=types.FunctionCall(name="multiply", args={"a": 7, "b": 3}))],
            [],
        ]
        for parts in cases:
            with self.subTest(parts=parts):
                reply = response(*parts)
                reply.candidates[0].finish_reason = types.FinishReason.MAX_TOKENS
                reply.usage_metadata.thoughts_token_count = 8
                client = scripted_client(reply)
                result = run_agent(client, "test-model", "Compute.", tools=[multiply])
                self.assertEqual(result.status, "output_limit")
                self.assertEqual(result.finish_reason, "MAX_TOKENS")
                self.assertEqual(result.answer, "")
                self.assertEqual(result.tool_calls, 0)
                self.assertEqual(result.model_events[0]["thought_tokens"], 8)
                self.assertNotIn("thought_signature", result.model_events[0])
                client.models.generate_content.assert_called_once()
                if parts and parts[0].text:
                    self.assertEqual(result.candidate_response, parts[0].text)

    def test_non_success_finish_reason_does_not_accept_visible_text(self):
        reply = response(types.Part(text="An incomplete or blocked answer."))
        reply.candidates[0].finish_reason = types.FinishReason.SAFETY
        client = scripted_client(reply)
        result = run_agent(client, "test-model", "Reply.")
        self.assertEqual(result.status, "response_stopped")
        self.assertEqual(result.finish_reason, "SAFETY")
        self.assertEqual(result.answer, "")
        client.models.generate_content.assert_called_once()

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
