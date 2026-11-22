"""Fixed evaluation snapshots, request-limited sessions, and resumable task queues."""

from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .budget import RequestBudgetExceeded
from .evidence import EVIDENCE_MODE, EVIDENCE_VERSION, EXCERPT_WORDS, MAX_EXCERPTS, MAX_EXCERPT_CHARS
from .config import PROJECT_ROOT
from .constraints import ANSWER_CONSTRAINT_VERSION
from .research import BENCHMARK_EXCLUDED_DOMAINS, MAX_SEARCH_REQUESTS, QUESTION_ECHO_WORDS, SEARCH_POLICY, TOOL_AVAILABILITY_VERSION, execute_research
from .web import utc_now


QUESTIONS_URL = "https://agents-course-unit4-scoring.hf.space/questions"
DEFAULT_EVAL_MODEL = "gemini-3.5-flash-lite"
BENCHMARK_INSTRUCTION = (
    "Follow the question's exact answer format. The JSON answer field must contain "
    "only the requested final answer: no FINAL ANSWER label, explanation, or citations. "
    "Put supporting quotations in evidence.\n\nQuestion:\n"
)
TERMINAL = {"answered", "unresolved", "unsupported"}


class EvaluationError(ValueError):
    """An evaluation cannot proceed with its current local inputs."""


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return sha256(canonical(value)).hexdigest()


def atomic_json(path: Path, value) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".checkpoint-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


@contextmanager
def evaluation_lock(directory: Path):
    # OS locks are released on process exit, including a crash. Keep the lock
    # file itself so another process never locks a replacement inode.
    if not directory.is_dir():
        raise EvaluationError("Prepare this evaluation before running or exporting it.")
    with (directory / ".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise EvaluationError("Another process is using this evaluation. Close it before resuming.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def evaluation_path(name: str, root: Path | None = None) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", name):
        raise EvaluationError("Use an evaluation name of 1-64 letters, digits, underscores, or hyphens.")
    return (Path(root) if root is not None else PROJECT_ROOT / "evaluations") / name


def normalize_questions(payload: list) -> list[dict]:
    if not isinstance(payload, list) or not 1 <= len(payload) <= 500:
        raise EvaluationError("The question snapshot must be a non-empty bounded list.")
    result, ids = [], set()
    for item in payload:
        if not isinstance(item, dict):
            raise EvaluationError("Every question must be an object.")
        task_id, question = item.get("task_id"), item.get("question")
        filename = item.get("file_name") or ""
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", task_id) or task_id in ids:
            raise EvaluationError("Task identifiers must be unique bounded strings.")
        if not isinstance(question, str) or not question.strip() or len(question) > 20_000:
            raise EvaluationError("Questions must contain 1-20,000 characters.")
        if not isinstance(filename, str) or len(filename) > 250 or "/" in filename or "\\" in filename or filename in (".", ".."):
            raise EvaluationError("Attachment names must be bounded filenames without directory paths.")
        ids.add(task_id)
        # Ground-truth/answer fields are deliberately not retained or supplied
        # to the agent, even if an upstream response acquires extra fields.
        result.append({"task_id": task_id, "question": question, "file_name": filename, "level": str(item.get("level", item.get("Level", "")))})
    return result


def fetch_course_questions() -> list[dict]:
    import httpx

    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            with client.stream("GET", QUESTIONS_URL) as response:
                if response.status_code != 200:
                    raise EvaluationError(f"The question endpoint returned HTTP {response.status_code}.")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 1024 * 1024:
                        raise EvaluationError("The question response exceeded 1 MiB.")
                    chunks.append(chunk)
        questions = normalize_questions(json.loads(b"".join(chunks)))
    except httpx.HTTPError:
        raise EvaluationError("The public question endpoint could not be reached. No model request was made.") from None
    except (json.JSONDecodeError, UnicodeError):
        raise EvaluationError("The question endpoint did not return valid JSON.") from None
    if len(questions) != 20:
        raise EvaluationError("The course advertises 20 questions; inspect the changed endpoint before preparing an evaluation.")
    return questions


def implementation_fingerprint() -> str:
    paths = ["traceagent/agent.py", "traceagent/research.py", "traceagent/evidence.py", "traceagent/constraints.py", "traceagent/web.py", "traceagent/tools.py", "traceagent/config.py", "traceagent/budget.py", "traceagent/evaluation.py", "traceagent/__main__.py", "uv.lock"]
    return digest({path: sha256((PROJECT_ROOT / path).read_text(encoding="utf-8").encode("utf-8")).hexdigest() for path in paths})


def input_kind(question: dict) -> str:
    if question["file_name"]:
        return "attachment"
    if re.search(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)(?:/|\b)", question["question"], re.I):
        return "video"
    return "text"


def prepare_evaluation(directory: Path, questions: list[dict], *, model: str = DEFAULT_EVAL_MODEL, search_backend: str = "serper", max_model_calls: int = 8, source_url: str = QUESTIONS_URL) -> dict:
    questions = normalize_questions(questions)
    if not isinstance(model, str) or not model or any(c.isspace() for c in model):
        raise EvaluationError("Choose a valid explicit model ID.")
    if search_backend not in {"ddgs", "serper", "tavily"} or type(max_model_calls) is not int or not 1 <= max_model_calls <= 8:
        raise EvaluationError("Choose an available search backend and 1-8 model calls per task.")
    if not isinstance(source_url, str) or not source_url.strip() or len(source_url) > 1000:
        raise EvaluationError("Provide a bounded, non-empty question source identifier.")
    profile = {"mode": "research", "model": model.removeprefix("models/"), "search_backend": search_backend, "max_model_calls": max_model_calls, "max_tool_calls": 12, "output_tokens_per_call": 4096, "answer_repairs": 1, "model_timeout_ms": 90_000, "benchmark_instruction": BENCHMARK_INSTRUCTION, "benchmark_source_filter": True, "question_evidence": True, "reserved_final_requests": 1, "final_response_mode": "schema_when_finalizing_or_correcting", "search_policy": "open_before_repeat", "focus_notice": True}
    profile.update(source_filter_version=2, question_echo_words=QUESTION_ECHO_WORDS, course_context_excluded=True, excluded_discussion_domains=list(BENCHMARK_EXCLUDED_DOMAINS))
    profile.update(search_policy=SEARCH_POLICY, read_before_search="guidance_only", tool_availability_version=TOOL_AVAILABILITY_VERSION, max_search_requests=MAX_SEARCH_REQUESTS)
    profile.update(reading_context="retained_passages", evidence_version=EVIDENCE_VERSION, evidence_mode=EVIDENCE_MODE, excerpt_words=EXCERPT_WORDS, max_excerpts_per_source=MAX_EXCERPTS, max_excerpt_chars=MAX_EXCERPT_CHARS)
    profile.update(answer_constraint_version=ANSWER_CONSTRAINT_VERSION, answer_constraint_mode="explicit_name_year_bound")
    tasks = []
    for question in questions:
        kind = input_kind(question)
        tasks.append({"task_id": question["task_id"], "input_kind": kind, "state": "pending" if kind == "text" else "unsupported", "reason": "" if kind == "text" else f"The current evaluation profile does not support {kind} inputs.", "submitted_answer": "", "attempts": []})
    manifest = {"schema_version": 1, "created_at": utc_now(), "source_url": source_url, "dataset_sha256": digest(questions), "profile": profile, "profile_sha256": digest(profile), "implementation_sha256": implementation_fingerprint(), "tasks": tasks, "sessions": []}
    try:
        directory.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise EvaluationError("This evaluation already exists. Resume it or choose a new name; snapshots are never overwritten.") from None
    atomic_json(directory / "questions.json", questions)
    atomic_json(directory / "manifest.json", manifest)
    return manifest


def load_evaluation(directory: Path) -> tuple[dict, list[dict]]:
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        questions = json.loads((directory / "questions.json").read_text(encoding="utf-8"))
        valid = manifest["schema_version"] == 1 and digest(questions) == manifest["dataset_sha256"] and digest(manifest["profile"]) == manifest["profile_sha256"]
        valid = valid and [q["task_id"] for q in questions] == [task["task_id"] for task in manifest["tasks"]]
        if not valid:
            raise EvaluationError("The evaluation snapshot or profile has changed; use a new evaluation instead of mixing results.")
        normalize_questions(questions)
        return manifest, questions
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        raise EvaluationError("The evaluation checkpoint is missing, incomplete, or invalid.") from None


def evaluation_summary(manifest: dict) -> dict:
    counts = Counter(task["state"] for task in manifest["tasks"])
    invalidated = bool(manifest.get("integrity_issues"))
    return {"total_tasks": len(manifest["tasks"]), "states": dict(counts), "answers_prepared": counts["answered"], "exportable_answers": 0 if invalidated else counts["answered"], "integrity_status": "invalidated" if invalidated else "not_audited", "integrity_issues": manifest.get("integrity_issues", []), "all_tasks_processed": all(task["state"] in TERMINAL for task in manifest["tasks"]), "requests_attempted": sum(session["requests_attempted"] for session in manifest["sessions"]), "official_score": None, "note": "Prepared answers are not graded correct answers. Unsupported and unfinished tasks remain in the denominator."}


def invalidate_evaluation(directory: Path, reason: str, *, task_id: str) -> dict:
    """Append an audit finding without rewriting any attempt, source, or answer."""
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 700:
        raise EvaluationError("Provide a bounded audit reason.")
    with evaluation_lock(directory):
        manifest, _ = load_evaluation(directory)
        if task_id not in {task["task_id"] for task in manifest["tasks"]}:
            raise EvaluationError("The audit finding must refer to an existing task.")
        issues = manifest.setdefault("integrity_issues", [])
        if not any(issue["task_id"] == task_id and issue["reason"] == reason.strip() for issue in issues):
            issues.append({"recorded_at": utc_now(), "task_id": task_id, "reason": reason.strip()})
        atomic_json(directory / "manifest.json", manifest)
        return manifest


class SessionBudget:
    """HTTPX hook: persist a conservative reservation before every SDK request."""

    def __init__(self, directory: Path, manifest: dict, session: dict):
        self.directory, self.manifest, self.session = directory, manifest, session
        self.attempt = None
        self.stop_scope = ""

    def before_request(self, request):
        if self.attempt is None:
            raise EvaluationError("A model request was attempted outside an active task.")
        if self.attempt["requests_attempted"] >= self.manifest["profile"]["max_model_calls"]:
            self.stop_scope = "task"
            raise RequestBudgetExceeded("Task request budget reached.")
        if self.session["requests_attempted"] >= self.session["request_budget"]:
            self.stop_scope = "session"
            raise RequestBudgetExceeded("Session request budget reached.")
        self.attempt["requests_attempted"] += 1
        self.session["requests_attempted"] += 1
        atomic_json(self.directory / "manifest.json", self.manifest)


def run_evaluation(directory: Path, settings, *, request_budget: int, max_tasks: int = 1, client_factory, research_runner=execute_research, on_event=None, on_task=None, on_result=None, error_formatter=None) -> dict:
    if type(request_budget) is not int or not 1 <= request_budget <= 1000 or type(max_tasks) is not int or not 1 <= max_tasks <= 500:
        raise EvaluationError("Use a request budget of 1-1,000 and a task limit of 1-500.")
    with evaluation_lock(directory):
        manifest, questions = load_evaluation(directory)
        if manifest.get("integrity_issues"):
            raise EvaluationError("This evaluation was invalidated by a source audit. Preserve it and prepare a new evaluation; its answers cannot be used for scoring.")
        if implementation_fingerprint() != manifest["implementation_sha256"]:
            raise EvaluationError("The implementation has changed. Prepare a new evaluation to keep configurations comparable.")
        profile = manifest["profile"]
        if settings.model != profile["model"] or settings.search_backend != profile["search_backend"]:
            raise EvaluationError("The supplied settings do not match the frozen evaluation profile.")
        # A crash may leave an in-flight attempt. Preserve it and retry the task
        # from its question, rather than silently claiming tool-level resume.
        for old_session in manifest["sessions"]:
            if old_session["state"] == "running":
                old_session.update(state="interrupted", stop_reason="process_interrupted", finished_at=utc_now())
        for task in manifest["tasks"]:
            if task["state"] == "running":
                task.update(state="retryable_error", reason="The prior process stopped during this task.")
                if task["attempts"]:
                    task["attempts"][-1].update(status="interrupted", finished_at=utc_now())
        session = {"session_id": uuid4().hex[:12], "started_at": utc_now(), "state": "running", "request_budget": request_budget, "requests_attempted": 0, "tasks_started": 0, "stop_reason": ""}
        manifest["sessions"].append(session)
        budget = SessionBudget(directory, manifest, session)
        atomic_json(directory / "manifest.json", manifest)
        by_id = {q["task_id"]: q for q in questions}
        current = None
        try:
            with client_factory(settings, timeout_ms=profile["model_timeout_ms"], before_request=budget.before_request) as client:
                for task in manifest["tasks"]:
                    if task["state"] in TERMINAL:
                        continue
                    if session["tasks_started"] >= max_tasks:
                        session["stop_reason"] = "task_limit"
                        break
                    remaining = request_budget - session["requests_attempted"]
                    if remaining < profile["max_model_calls"]:
                        session["stop_reason"] = "request_budget_reserved"
                        break
                    current = task
                    attempt = {"started_at": utc_now(), "status": "running", "requests_attempted": 0}
                    task["attempts"].append(attempt)
                    task.update(state="running", reason="")
                    budget.attempt = attempt
                    budget.stop_scope = ""
                    session["tasks_started"] += 1
                    atomic_json(directory / "manifest.json", manifest)
                    if on_task is not None:
                        on_task(task["task_id"])
                    question = by_id[task["task_id"]]["question"]
                    record, path = research_runner(client, settings, BENCHMARK_INSTRUCTION + question, directory=directory / "records", max_model_calls=profile["max_model_calls"], on_event=on_event, error_formatter=error_formatter, benchmark_mode=True, question_source=question)
                    attempt.update({key: record.get(key) for key in ("status", "reason", "model_calls", "tool_calls", "answer_repairs", "input_tokens", "total_tokens", "elapsed_seconds", "provider_http_status", "provider_error_type")})
                    attempt.update(finished_at=utc_now(), run_record=str(Path(path).relative_to(directory)))
                    task["reason"] = record.get("reason", "")
                    search_errors = {action.get("error_code") for action in record.get("actions", [])}
                    if record["status"] == "provider_error":
                        task["state"] = "retryable_error"
                        session["stop_reason"] = "provider_quota" if record.get("provider_http_status") == 429 else "provider_error"
                    elif record["status"] == "execution_error":
                        task["state"], session["stop_reason"] = "retryable_error", "execution_error"
                    elif search_errors & {"search_quota", "search_auth"}:
                        task["state"], session["stop_reason"] = "retryable_error", "search_configuration_or_quota"
                    elif record["status"] == "request_budget" and budget.stop_scope != "task":
                        task["state"], session["stop_reason"] = "retryable_error", "request_budget"
                    else:
                        task["state"] = "answered" if record["status"] == "answered" else "unresolved"
                        task["submitted_answer"] = record["answer"] if task["state"] == "answered" else ""
                    atomic_json(directory / "manifest.json", manifest)
                    current = None
                    if on_result is not None:
                        on_result(record)
                    if session["stop_reason"]:
                        break
                else:
                    session["stop_reason"] = "all_tasks_processed"
        except KeyboardInterrupt:
            session["stop_reason"] = "interrupted"
            raise
        except Exception as error:
            session.update(stop_reason="local_error", error_type=type(error).__name__)
            raise EvaluationError("Evaluation stopped on a local error; its checkpoint and reserved requests were preserved.") from None
        finally:
            if current is not None and current["state"] == "running":
                current.update(state="retryable_error", reason="The task was interrupted; its attempted requests were preserved.")
                current["attempts"][-1].update(status="interrupted", finished_at=utc_now())
            session.update(state="finished", finished_at=utc_now())
            atomic_json(directory / "manifest.json", manifest)
        return manifest


def export_evaluation(directory: Path) -> tuple[Path, Path]:
    with evaluation_lock(directory):
        manifest, _ = load_evaluation(directory)
        invalidated = bool(manifest.get("integrity_issues"))
        answers = [{"task_id": task["task_id"], "submitted_answer": task["submitted_answer"] if task["state"] == "answered" and not invalidated else ""} for task in manifest["tasks"]]
        report = {**evaluation_summary(manifest), "draft": invalidated or not all(task["state"] in TERMINAL for task in manifest["tasks"]), "profile": manifest["profile"], "dataset_sha256": manifest["dataset_sha256"], "implementation_sha256": manifest["implementation_sha256"]}
        atomic_json(directory / "answers.json", answers)
        atomic_json(directory / "report.json", report)
    return directory / "answers.json", directory / "report.json"
