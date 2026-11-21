"""A bounded LangGraph model/tool loop using the existing Google SDK client."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
from time import perf_counter
from typing import Callable, TypedDict

from google.genai import types
from langgraph.graph import END, START, StateGraph

from .tools import TOOLS, ToolError


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
    model_events: list[dict]
    candidate_response: str
    answer_repairs: int
    validation_events: list[dict]
    permitted_tools: list[str]
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
    model_events: list[dict] = field(default_factory=list)
    candidate_response: str = ""
    answer_repairs: int = 0
    validation_events: list[dict] = field(default_factory=list)

    @property
    def finish_reason(self) -> str:
        return self.model_events[-1]["finish_reason"] if self.model_events else ""


class AgentRequestError(Exception):
    """Retain completed tool activity when a model request fails."""

    def __init__(self, provider_error: Exception, request_number: int, tool_calls: int, events: list[dict], input_tokens: int = 0, total_tokens: int = 0, model_events: list[dict] | None = None, answer_repairs: int = 0, validation_events: list[dict] | None = None, candidate_response: str = ""):
        super().__init__("An agent model request failed.")
        self.provider_error = provider_error
        self.request_number = request_number
        self.tool_calls = tool_calls
        self.events = list(events)
        self.input_tokens = input_tokens
        self.total_tokens = total_tokens
        self.model_events = list(model_events or [])
        self.answer_repairs = answer_repairs
        self.validation_events = list(validation_events or [])
        self.candidate_response = candidate_response


def build_graph(
    client,
    model: str,
    tools: list[Callable] | None = None,
    max_model_calls: int = 4,
    max_tool_calls: int = 6,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    max_output_tokens: int = 1024,
    thinking_level: str | None = None,
    final_validator: Callable | None = None,
    max_answer_repairs: int = 1,
    final_response_schema: dict | None = None,
    reserve_final_call: bool = False,
    tool_policy: Callable[[], dict[str, str]] | None = None,
    on_event: Callable | None = None,
):
    """Compile the graph; this does not make a model request."""
    if not 1 <= max_model_calls <= 8 or not 1 <= max_tool_calls <= 12:
        raise ValueError("Call limits must be 1-8 model calls and 1-12 tool calls.")
    if max_answer_repairs not in (0, 1):
        raise ValueError("Allow zero or one final-answer correction.")
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
        system_instruction=system_prompt,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        automatic_continuation=False,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_level=thinking_level.upper()) if thinking_level is not None else None,
    )
    repair_config = generation_config.model_copy(update={
        "tool_config": types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="NONE")),
    })
    final_config = generation_config.model_copy(update={
        "tools": None, "tool_config": None,
        "response_mime_type": "application/json" if final_response_schema is not None else None,
        "response_json_schema": final_response_schema,
    })
    if final_response_schema is not None:
        repair_config = final_config

    def restrictions() -> dict[str, str]:
        blocked = {} if tool_policy is None else dict(tool_policy())
        if not set(blocked) <= registry.keys() or any(not isinstance(code, str) or not code for code in blocked.values()):
            raise ValueError("Tool policy must map registered tool names to reason codes.")
        return blocked

    def model_node(state: AgentState) -> dict:
        finalizing = reserve_final_call and not state["answer_repairs"] and (
            state["model_calls"] == max_model_calls - 1 or state["tool_calls"] >= max_tool_calls
        )
        phase = "answer_correction" if state["answer_repairs"] else "finalization" if finalizing else "normal"
        contents = state["contents"]
        if finalizing:
            trigger = "last_request" if state["model_calls"] == max_model_calls - 1 else "tool_limit"
            contents = [*contents, types.Content(role="user", parts=[types.Part(text=(
                "Finish now using only the question and observations already available. "
                "No further tools are available. Return the required final response. "
                "If existing evidence is insufficient, return status unresolved with "
                "an empty answer/evidence and a brief reason. Do not invent facts or "
                "claim that unavailable evidence was checked."
            ))])]
            if on_event is not None:
                on_event({"tool": "answer_finalize", "trigger": trigger})
        config = repair_config if state["answer_repairs"] else final_config if finalizing else generation_config
        blocked = restrictions() if phase == "normal" else {}
        permitted = [name for name in registry if name not in blocked] if phase == "normal" else []
        if phase == "normal" and blocked:
            active = [declaration for declaration in declarations if declaration.name in permitted]
            config = generation_config.model_copy(update={
                "tools": [types.Tool(function_declarations=active)] if active else None,
            })
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config,
            )
        except Exception as error:
            raise AgentRequestError(
                error, state["model_calls"] + 1, state["tool_calls"], state["events"],
                state["input_tokens"], state["total_tokens"], model_events=state["model_events"],
                answer_repairs=state["answer_repairs"], validation_events=state["validation_events"],
                candidate_response=state["candidate_response"],
            ) from error
        calls = state["model_calls"] + 1
        usage = response.usage_metadata
        candidates = response.candidates or []
        candidate = candidates[0] if candidates else None
        content = candidate.content if candidate else None
        reason = candidate.finish_reason if candidate else None
        reason = getattr(reason, "value", reason) or ""
        parts = content.parts if content and content.parts else []
        visible = "".join(part.text for part in parts if part.text and not part.thought).strip()
        model_event = {
            "request_number": calls, "finish_reason": reason,
            "phase": phase,
            "available_tools": permitted,
            "tool_restrictions": blocked,
            "input_tokens": usage.prompt_token_count if usage else None,
            "total_tokens": usage.total_token_count if usage else None,
            "output_tokens": usage.candidates_token_count if usage else None,
            "thought_tokens": usage.thoughts_token_count if usage else None,
        }
        update = {
            "model_calls": calls,
            "input_tokens": state["input_tokens"] + (usage.prompt_token_count or 0 if usage else 0),
            "total_tokens": state["total_tokens"] + (usage.total_token_count or 0 if usage else 0),
            "model_events": [*state["model_events"], model_event],
            "candidate_response": visible,
            "permitted_tools": permitted,
        }
        # Reject cut-off output before accepting text or executing any tool calls.
        # A syntactically valid fragment can still be semantically incomplete.
        if reason == "MAX_TOKENS":
            return {**update, "pending": [], "answer": "", "status": "output_limit"}
        if reason not in ("", "STOP", "FINISH_REASON_UNSPECIFIED"):
            return {**update, "pending": [], "answer": "", "status": "response_stopped"}
        if not parts:
            return {**update, "pending": [], "status": "empty_response"}
        # Keep the full original content, including thought signatures needed by
        # Gemini follow-up calls. Only actions/results are shown in the CLI.
        pending = [part.function_call for part in parts if part.function_call]
        update["contents"] = [*contents, content]
        if pending:
            if state["answer_repairs"]:
                return {**update, "pending": [], "answer": "", "status": "repair_tool_request"}
            if finalizing:
                return {**update, "pending": [], "answer": "", "status": "finalization_tool_request"}
            if calls >= max_model_calls or state["tool_calls"] + len(pending) > max_tool_calls:
                return {**update, "pending": [], "status": "limit_reached"}
            return {**update, "pending": pending, "status": "running"}
        answer = visible
        return {
            **update, "pending": [], "answer": answer,
            "status": "complete" if answer else "empty_response",
        }

    def tool_node(state: AgentState) -> dict:
        parts = []
        events = []
        for call in state["pending"]:
            started = perf_counter()
            started_at = datetime.now(timezone.utc).isoformat()
            function = registry.get(call.name)
            arguments = call.args or {}
            if function is None:
                payload = {"error": "Unknown tool. Choose one of the declared tools."}
            elif call.name not in state["permitted_tools"] or call.name in restrictions():
                # Recheck each call: one response can contain several searches,
                # and an earlier call may change availability within that batch.
                payload = {"error": "This tool is unavailable in the current state. Use the tools declared for the next request, or finish from existing evidence.", "error_code": "tool_unavailable"}
            else:
                try:
                    inspect.signature(function).bind(**arguments)
                    payload = {"result": function(**arguments)}
                except ToolError as error:
                    payload = {"error": str(error), "error_code": error.code}
                except (TypeError, ValueError, OverflowError, ZeroDivisionError):
                    payload = {"error": "Invalid arguments or non-finite arithmetic result."}
            parts.append(types.Part(function_response=types.FunctionResponse(
                name=call.name, id=call.id, response=payload,
            )))
            event = {"tool": call.name, "arguments": arguments, **payload, "started_at": started_at, "elapsed_ms": round((perf_counter() - started) * 1000, 2)}
            events.append(event)
            if on_event is not None:
                on_event(event)
        return {
            # Gemini generateContent accepts functionResponse parts in a user
            # turn. A Chat Completions-style "tool" role is rejected here.
            "contents": [*state["contents"], types.Content(role="user", parts=parts)],
            "pending": [],
            "tool_calls": state["tool_calls"] + len(events),
            "events": [*state["events"], *events],
        }

    def review_node(state: AgentState) -> dict:
        verdict = final_validator(state["answer"])
        invalid = verdict.get("status") in {"format_error", "evidence_error"}
        repair = invalid and state["answer_repairs"] < max_answer_repairs and state["model_calls"] < max_model_calls
        reason = str(verdict.get("reason") or "")[:700]
        event = {"after_model_call": state["model_calls"], "status": verdict.get("status"), "reason": reason, "repair_scheduled": repair}
        update = {"validation_events": [*state["validation_events"], event]}
        if invalid and on_event is not None:
            on_event({"tool": "answer_check", "error": reason, "error_code": verdict["status"], "repair_scheduled": repair})
        if not repair:
            return update
        feedback = (
            "Final-answer validation failed: " + reason + "\n"
            "Return a corrected complete JSON object using the question, tool results, "
            "and source passages already in this conversation. Tools are disabled for "
            "this correction. Keep the answer factual and concise. Cite Q1 only for "
            "supplied question inputs, or source IDs opened by tools, with exact "
            "supporting excerpts. Escape quotation marks inside JSON strings. "
            "Apply only output transformations the question explicitly requests. "
            "Shorten quotes without changing "
            "their meaning; all quotes from the same source URL must total at most "
            "25 words. Never invent missing evidence. If the saved evidence cannot "
            "support an answer, return status unresolved with an empty answer/evidence "
            "and a brief reason. Return only the corrected JSON object."
        )
        return {
            **update, "answer_repairs": state["answer_repairs"] + 1,
            "contents": [*state["contents"], types.Content(role="user", parts=[types.Part(text=feedback)])],
            "status": "repairing",
        }

    graph = StateGraph(AgentState)
    graph.add_node("model", model_node)
    graph.add_node("tools", tool_node)
    if final_validator is not None:
        graph.add_node("review", review_node)
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model", lambda state: "tools" if state["pending"] else "review" if final_validator is not None and state["status"] == "complete" else "end",
        {"tools": "tools", "review": "review", "end": END} if final_validator is not None else {"tools": "tools", "end": END},
    )
    graph.add_edge("tools", "model")
    if final_validator is not None:
        graph.add_conditional_edges("review", lambda state: "model" if state["status"] == "repairing" else "end", {"model": "model", "end": END})
    return graph.compile()


def run_agent(
    client,
    model: str,
    question: str,
    tools: list[Callable] | None = None,
    max_model_calls: int = 4,
    max_tool_calls: int = 6,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    max_output_tokens: int = 1024,
    thinking_level: str | None = None,
    final_validator: Callable | None = None,
    max_answer_repairs: int = 1,
    final_response_schema: dict | None = None,
    reserve_final_call: bool = False,
    tool_policy: Callable[[], dict[str, str]] | None = None,
    on_event: Callable | None = None,
) -> AgentResult:
    if not question.strip():
        raise ValueError("Provide a non-empty question.")
    graph = build_graph(client, model, tools, max_model_calls, max_tool_calls, system_prompt=system_prompt, max_output_tokens=max_output_tokens, thinking_level=thinking_level, final_validator=final_validator, max_answer_repairs=max_answer_repairs, final_response_schema=final_response_schema, reserve_final_call=reserve_final_call, tool_policy=tool_policy, on_event=on_event)
    initial = AgentState(
        contents=[types.Content(role="user", parts=[types.Part(text=question)])],
        model_calls=0, tool_calls=0, input_tokens=0, total_tokens=0,
        pending=[], events=[], model_events=[], candidate_response="", answer="", status="running",
        answer_repairs=0, validation_events=[],
        permitted_tools=[],
    )
    final = graph.invoke(initial, config={"recursion_limit": 2 * max_model_calls + 2})
    return AgentResult(
        answer=final["answer"], status=final["status"],
        model_calls=final["model_calls"], tool_calls=final["tool_calls"],
        input_tokens=final["input_tokens"], total_tokens=final["total_tokens"],
        events=final["events"], model_events=final["model_events"],
        candidate_response=final["candidate_response"],
        answer_repairs=final["answer_repairs"], validation_events=final["validation_events"],
    )
