# TraceAgent: system design

Status: proposed architecture with a working calculator agent at its core. Updated 2026-11-15.

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
| Tool layer | Execute research, document-reading, and arithmetic functions | Multiply/add implemented; research tools planned |
| Evidence record | Store source identifiers, excerpts or file locations, retrieval times, and related actions | Planned; current tool events remain in memory and terminal output |
| Answer checks | Check format constraints and review whether the evidence supports the proposed answer | Planned |
| Answer formatter | Produce a useful demo response or a benchmark-only answer field | Current CLI output exists; separate output modes planned |
| Evaluation runner | Run a fixed task set, save results, compare configurations, and prepare scoring submissions | Planned |
| Demo interface | Let visitors ask questions and inspect sources, actions, and evaluation results | Gradio interface planned |

## Proposed data flow

```mermaid
flowchart TD
    Q["Question or benchmark task"] --> A["Agent controller"]
    A --> T["Research and calculation tools"]
    T --> E["Evidence and action record"]
    E --> A
    A --> V["Answer checks"]
    V -->|More evidence| A
    V -->|Ready| F["Answer formatter"]
    F --> O["Demo or scoring output"]
```

The controller remains responsible for choosing the next action. Tools execute specific functions and return observations. The evidence record makes it possible to inspect the basis for an answer. Answer checks combine deterministic format validation with an evidence review; they reduce failures but do not guarantee factual correctness. A return to research must remain inside the run's resource budget.

## Initial design decisions

| Decision | Reason and implication |
| --- | --- |
| One agent controller | Establish a measurable baseline with a small number of moving parts; evaluate further architectural complexity against observed failures |
| Explicit Python tools | Separate model-selected actions from execution, validation, and result logging |
| Preserve full model messages | Keep protocol state, including Gemini function-call identifiers and thought signatures |
| Evidence per run | Make sources and actions inspectable; a shared retrieval database can be considered if document scale justifies it |
| Distinct demo and scoring outputs | Let people inspect sources without adding explanation or citation text to an exact-match answer |
| Free-tier Gemini 3.6 Flash initially | A live model connection and multiplication loop succeeded; availability and quota remain service constraints |
| Bounded execution | The current calculator loop permits up to four model calls and six tool calls; research budgets will be chosen after inspecting task requirements |

## Failure behavior

Transient provider failures should produce bounded retries or an explicit stopped run. Quota limits must not trigger a paid provider. Invalid tool arguments return structured errors so the controller can recover within its budget. Website and document contents are treated as retrieved data, not as permission to change system rules. Later web tools must enforce timeouts, content-size limits, and URL-access restrictions.

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

Next, define the research workflow and its acceptance criteria, inspect the benchmark's required input types, and select the first free search/page-reading tools. The architecture above is a design baseline to review and refine before those components are built.
