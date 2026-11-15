"""A bounded LangGraph model/tool loop using the existing Google SDK client."""

from dataclasses import dataclass
import inspect
from typing import Callable, TypedDict

from google.genai import types
from langgraph.graph import END, START, StateGraph

from .tools import TOOLS


SYSTEM_PROMPT = (
    "You are TraceAgent, a research agent at the calculator-tool learning milestone. "
    "Use the available arithmetic tools for arithmetic operations they support. "
    "Read tool results before giving your final answer. "
    "If a required operation has no tool, say which tool is missing instead of inventing a result. "
    "Give a concise final answer."
)


class AgentState(TypedDict):
    contents: list[types.Content]
    model_calls: int
    tool_calls: int
    input_tokens: int
    total_tokens: int
    pending: list[types.FunctionCall]
    events: list[dict]
    answer: str
    status: str


@dataclass(frozen=True)
class AgentResult:
    answer: str
    status: str
    model_calls: int
    tool_calls: int
    input_tokens: int
    total_tokens: int
    events: list[dict]


class AgentRequestError(Exception):
    """Retain completed tool activity when a model request fails."""

    def __init__(self, provider_error: Exception, request_number: int, tool_calls: int, events: list[dict]):
        super().__init__("An agent model request failed.")
        self.provider_error = provider_error
        self.request_number = request_number
        self.tool_calls = tool_calls
        self.events = list(events)


def build_graph(
    client,
    model: str,
    tools: list[Callable] | None = None,
    max_model_calls: int = 4,
    max_tool_calls: int = 6,
):
    """Compile the graph; this does not make a model request."""
    if not 1 <= max_model_calls <= 8 or not 1 <= max_tool_calls <= 12:
        raise ValueError("Call limits must be 1-8 model calls and 1-12 tool calls.")
    available = list(TOOLS if tools is None else tools)
    registry = {function.__name__: function for function in available}
    if not available or len(registry) != len(available):
        raise ValueError("Provide at least one tool, with unique function names.")
    declarations = [
        types.FunctionDeclaration.from_callable(client=client, callable=function, use_json_schema=True)
        for function in available
    ]
    for declaration in declarations:
        # Callable conversion also infers a bare Python return schema. Our tool
        # responses use {result: ...} or {error: ...}, so omit that optional schema.
        declaration.response = None
        declaration.response_json_schema = None
    generation_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        max_output_tokens=1024,
    )

    def model_node(state: AgentState) -> dict:
        try:
            response = client.models.generate_content(
                model=model, contents=state["contents"], config=generation_config,
            )
        except Exception as error:
            raise AgentRequestError(
                error, state["model_calls"] + 1, state["tool_calls"], state["events"],
            ) from error
        calls = state["model_calls"] + 1
        usage = response.usage_metadata
        update = {
            "model_calls": calls,
            "input_tokens": state["input_tokens"] + (usage.prompt_token_count or 0 if usage else 0),
            "total_tokens": state["total_tokens"] + (usage.total_token_count or 0 if usage else 0),
        }
        candidates = response.candidates or []
        content = candidates[0].content if candidates else None
        if not content or not content.parts:
            return {**update, "pending": [], "status": "empty_response"}
        # Keep the full original content, including thought signatures needed by
        # Gemini follow-up calls. Only actions/results are shown in the CLI.
        pending = [part.function_call for part in content.parts if part.function_call]
        update["contents"] = [*state["contents"], content]
        if pending:
            if calls >= max_model_calls or state["tool_calls"] + len(pending) > max_tool_calls:
                return {**update, "pending": [], "status": "limit_reached"}
            return {**update, "pending": pending, "status": "running"}
        answer = "".join(
            part.text for part in content.parts if part.text and not part.thought
        ).strip()
        return {
            **update, "pending": [], "answer": answer,
            "status": "complete" if answer else "empty_response",
        }

    def tool_node(state: AgentState) -> dict:
        parts = []
        events = []
        for call in state["pending"]:
            function = registry.get(call.name)
            arguments = call.args or {}
            if function is None:
                payload = {"error": "Unknown tool. Choose one of the declared tools."}
            else:
                try:
                    inspect.signature(function).bind(**arguments)
                    payload = {"result": function(**arguments)}
                except (TypeError, ValueError, OverflowError, ZeroDivisionError):
                    payload = {"error": "Invalid arguments or non-finite arithmetic result."}
            parts.append(types.Part(function_response=types.FunctionResponse(
                name=call.name, id=call.id, response=payload,
            )))
            events.append({"tool": call.name, "arguments": arguments, **payload})
        return {
            # Gemini generateContent accepts functionResponse parts in a user
            # turn. A Chat Completions-style "tool" role is rejected here.
            "contents": [*state["contents"], types.Content(role="user", parts=parts)],
            "pending": [],
            "tool_calls": state["tool_calls"] + len(events),
            "events": [*state["events"], *events],
        }

    graph = StateGraph(AgentState)
    graph.add_node("model", model_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model", lambda state: "tools" if state["pending"] else "end",
        {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "model")
    return graph.compile()


def run_agent(
    client,
    model: str,
    question: str,
    tools: list[Callable] | None = None,
    max_model_calls: int = 4,
    max_tool_calls: int = 6,
) -> AgentResult:
    if not question.strip():
        raise ValueError("Provide a non-empty question.")
    graph = build_graph(client, model, tools, max_model_calls, max_tool_calls)
    initial = AgentState(
        contents=[types.Content(role="user", parts=[types.Part(text=question)])],
        model_calls=0, tool_calls=0, input_tokens=0, total_tokens=0,
        pending=[], events=[], answer="", status="running",
    )
    final = graph.invoke(initial, config={"recursion_limit": 2 * max_model_calls + 2})
    return AgentResult(
        answer=final["answer"], status=final["status"],
        model_calls=final["model_calls"], tool_calls=final["tool_calls"],
        input_tokens=final["input_tokens"], total_tokens=final["total_tokens"],
        events=final["events"],
    )
