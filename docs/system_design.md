# TraceAgent: system design

Status: proposed full architecture with a working calculator and a live search/read/answer research path. Updated 2026-11-17. See [requirements](requirements.md) and the [research walkthrough](research_walkthrough.md) for scope and observed evidence.

## Purpose and ownership

TraceAgent will investigate factual questions using tools, retain the evidence used to answer them, and produce a concise answer. It will support both an interactive research demonstration and evaluation on the Hugging Face Agents Course's 20-question GAIA validation subset.

Habib directs the system requirements, architecture choices, capability priorities, evaluation design, and demonstration experience. Coding assistance handles implementation, integration, debugging, and automated tests. Reviews focus on what components do, why they exist, how data flows, and which tradeoffs the evaluation supports.

## Requirements

| Requirement | Intended behavior |
| --- | --- |
| Research | Search the web, read relevant pages, and use supplied documents when needed |
| Tool use | Select actions from the question and intermediate results; repeat when more evidence is needed |
| Evidence | Associate retrieved facts with URLs or file locations and tool calls |
| Answers | Show supporting sources in the demo; send only the requested answer to benchmark scoring |
| Reliability | Bound calls and timeouts, retain completed actions after failures, and report unresolved tasks |
| Cost | Use free service tiers and local processing; stop at quota limits without paid fallback |
| Evaluation | Report correctness, runtime, model/tool usage, and failure categories on a clearly identified task set |
| Reproducibility | Record model and tool configuration, questions, generated answers, and run metadata |

## Components and current status

| Component | Responsibility | Status |
| --- | --- | --- |
| Task intake | Accept the question, attachments, and required answer format | CLI question intake exists; attachment handling planned |
| Agent controller | Decide which tool to use, read results, and decide whether to continue | LangGraph model/tool loop implemented |
| Tool layer | Execute research, document-reading, and arithmetic functions | Multiply/add, web/text/PDF reading, and selectable search adapters implemented; live Serper search, HTML/PDF reading, and multiplication observed; attachment routing remains planned |
| Evidence record | Store source identifiers, excerpts or file locations, retrieval times, and related actions | Web source IDs, separate supplied-question evidence (Q1), and JSON records implemented |
| Answer checks | Check format constraints and review whether the evidence supports the proposed answer | JSON, source-ID, and quote-membership checks can guide one budgeted correction with tools disabled; factual entailment remains a review task |
| Answer formatter | Produce a useful demo response or a benchmark-only answer field | CLI evidence output and evaluation answer-only exports implemented |
| Evaluation runner | Run a fixed task set, save results, compare configurations, and prepare scoring submissions | Research-profile snapshots, bounded batches, task-level resume, and draft exports implemented; model-only comparison and official scoring pending |
| Demo interface | Let visitors ask questions and inspect sources, actions, and evaluation results | Gradio interface planned |

## Proposed data flow

```mermaid
flowchart TD
    Q["Question or benchmark task"] --> A["Agent controller"]
    A --> T["Research and calculation tools"]
    T --> E["Evidence and action record"]
    E --> A
    A --> V["Answer checks"]
    V -->|One correction| A
    V -->|Ready| F["Answer formatter"]
    F --> O["Demo or scoring output"]
```

The controller remains responsible for choosing the next action. Tools execute specific functions and return observations. The evidence record makes it possible to inspect the basis for an answer. Answer checks combine deterministic format validation with an evidence review; they reduce failures but do not guarantee factual correctness. The implemented review path allows one final-answer correction inside the existing model-call budget, using retained observations and a precise validation message. Tool calls are disabled for that correction. A second validation failure, a provider error, or exhausted budget ends the run. This corrects formatting/provenance failures without assuming the answer is factually correct.

## Initial design decisions

| Decision | Reason and implication |
| --- | --- |
| One agent controller | Establish a measurable baseline with a small number of moving parts; evaluate further architectural complexity against observed failures |
| Explicit Python tools | Separate model-selected actions from execution, validation, and result logging |
| Preserve full model messages | Keep protocol state, including Gemini function-call identifiers and thought signatures |
| Evidence per run | Make sources and actions inspectable; a shared retrieval database can be considered if document scale justifies it |
| Selectable search provider | Keep source discovery independent of reading/evidence checks; Serper is available after Tavily signup returned 403, with explicit configuration and no automatic provider switch |
| Distinct demo and scoring outputs | Let people inspect sources without adding explanation or citation text to an exact-match answer |
| Free-tier Gemini 3.6 Flash initially | A live model connection and multiplication loop succeeded; availability and quota remain service constraints |
| Bounded execution | Calculator runs permit four model calls and six tools; research permits eight model calls and twelve tools, including at most one final-answer correction |

## Failure behavior

Provider failures stop the current run without automatic transport retries or a paid fallback. The single final-answer correction applies to a completed model response that fails format/evidence checks, and it remains inside the model-call budget. Invalid tool arguments return structured errors so the controller can recover within its budget. Website and document contents are treated as retrieved data, not as permission to change system rules. Web tools enforce timeouts, content-size limits, and URL-access restrictions.

If the evidence is incomplete or contradictory, the agent should seek additional evidence within its budget, then report the unresolved task. An answer-checking model is not a substitute for external ground truth.

## Evaluation and portfolio evidence

1. Keep a model-only baseline and a tool-enabled configuration, documenting the inputs and capabilities available to each.
2. Snapshot the evaluated question set and record model IDs, tool configuration, budgets, generated answers, and run metadata.
3. Report the course subset's exact-match score as a fraction of all 20 tasks; classify failed and unresolved runs explicitly.
4. Compare accuracy with runtime, input/total tokens, tool calls, and failure categories. A score alone does not explain reliability.
5. Use additional independently checked tasks to probe behavior beyond the course subset. Do not present a small validation result as full GAIA performance.
6. Generate benchmark answers through the agent rather than hard-coding answers or retrieving published solution lists.

The portfolio will include the source repository, a usable demonstration, an architecture explanation, reproducible evaluation instructions, selected action/source traces, and a candid results report. Public examples must be curated to exclude credentials and private inputs.

## Current evidence and next design work

A user-run multiplication task returned 391 with two model calls and one Python tool call. The run took 3.23 seconds and reported 368 input tokens and 470 total tokens. This verifies one end-to-end arithmetic path. Addition is implemented and dependent tool use is checked offline; it has not yet been observed live.

The benchmark inventory and acceptance criteria are recorded in [requirements.md](requirements.md). A live URL-supplied research example is documented in [research_walkthrough.md](research_walkthrough.md). The owner has also reported a complete Serper search/read/answer run: three model calls, two tool calls, 7,406 input tokens, 8,470 total tokens, and 66.62 seconds, with a directly supporting excerpt from official Python documentation. This is a single integration example. A later directly inspected Gemini 3.5 Flash-Lite run completed PDF research and multiplication: five model calls, three tool calls, one citation correction, 13,625 input tokens, 14,030 total tokens, and 81.87 seconds. Its two final supporting quotes total 19 words and match PDF pages 3 and 5. These are individual integration observations. The quota-aware evaluator is now implemented and completed a first one-task batch using seven HTTP request attempts. It retains all 20 tasks, including seven unsupported inputs. A subsequent source audit found benchmark answer leakage in the second task, invalidating v1. The replacement v2 profile permits Q1 evidence for self-contained reasoning and filters recognizable benchmark solutions at the tool boundary. Its question-only snapshot started fresh. The first replacement task prepared one ungraded answer using Wikipedia sources and eight requests. The source-filter block and Q1 reasoning paths still await live observation. Next, continue the fixed baseline and extend input handling.
