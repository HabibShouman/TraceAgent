# TraceAgent: requirements and next milestone

Design baseline, updated 2026-11-16. Research tools and source records are now implemented; observed and pending live checks are separated in the [research walkthrough](research_walkthrough.md). The benchmark runner remains planned.

## Product purpose

A research assistant that answers factual questions using web and file evidence, lets a person inspect its actions and sources, and can be evaluated reproducibly. The same controller will serve interactive use and the course benchmark, with distinct output formatting.

The owner leads requirements and architecture decisions and reviews observed behavior. Coding assistance implements and tests the agreed system. Work stays within free service tiers.

## Benchmark input inventory

The public question endpoint was inspected on 2026-11-16. The following categories describe the delivered input form, not the full set of skills each task requires.

| Primary delivered input | Tasks |
| --- | ---: |
| Question text without an attachment or video link | 13 |
| Attached image | 1 |
| Attached audio | 2 |
| Attached Python file | 1 |
| Attached Excel file | 1 |
| YouTube video link | 2 |
| Total | 20 |

Source: [live question endpoint](https://agents-course-unit4-scoring.hf.space/questions). Questions and ground-truth answers are not embedded in application logic. Text-delivered questions can still require web research and document retrieval. Unsupported input types must remain visible in full-set evaluation results.

## Inputs and outputs

| Area | Required behavior |
| --- | --- |
| Input | Accept a question, required response format, and optional file/reference |
| Interactive answer | Provide the answer, supporting sources/file locations, and a concise explanation |
| Benchmark answer | Supply the requested answer string alone in the submission field |
| Evidence | Associate used facts with source identifiers, retrieved text or file locations, and tool calls |
| Run record | Save configuration, actions, answer/status, runtime, available token counts, and errors |
| Unresolved task | Report the reason for stopping; do not silently replace unsupported tasks with fabricated answers |

## Capability roadmap

| Stage | Capability | Evidence needed to move on |
| --- | --- | --- |
| Working core | Model connection, multiplication, addition, bounded tool loop | Live multiplication observed; dependent arithmetic covered by offline tests |
| Current: web research | Free search adapters, webpage/PDF reading, source records | Live URL-supplied answer observed; configure Serper's free signup allowance and validate source discovery next |
| File handling | Route and read spreadsheets, images, audio, and code text | Validate each supported input type on independently checked examples |
| Baseline evaluation | Snapshot all 20 tasks, retain per-task results, prepare score submission | Report every task's status and the observed course-subset score |
| Targeted improvements | Address failure categories, including video access when justified | Compare new runs against the recorded baseline and report remaining limits |
| Portfolio demo | Usable interface, architecture explanation, result table, selected traces | A reviewer can understand and reproduce at least one complete research workflow |

Image/audio routing and code execution strategy need design and validation. Reading a Python file does not imply permission to execute arbitrary code. Video questions remain in scope for failure analysis even before video support exists.

## Immediate research milestone

Implement a small complete workflow: the agent receives a fresh factual question, searches for relevant material, opens a source, follows a relevant document link when needed, extracts the supporting detail, and returns an answer with its evidence. Use a non-benchmark example for this development demonstration.

Acceptance criteria:

1. At least one relevant source is opened and read; search snippets alone do not establish completion.
2. The cited URL or document location can be traced to a tool result and a supporting passage.
3. The agent's decisions depend on retrieved observations; the application contains no canned answer for the question.
4. A run record retains tool successes and failures, available usage, runtime, and the final status.
5. Missing evidence, inaccessible pages, provider failures, and exhausted budgets produce clear outcomes.
6. The output formatter can keep citations and explanations outside a benchmark answer field.
7. The run uses free services with bounded requests and no paid fallback.

The owner will review the question, sources, actions, answer quality, and failure behavior rather than write implementation functions. This review determines whether the workflow is useful and the design needs adjustment.

## Evaluation and public presentation

Keep a model-only comparison and a tool-enabled configuration, with documented inputs and limits. Count failed and unsupported tasks in the complete 20-task report. Record model/tool versions, budgets, and run dates, and use additional independently checked questions beyond the course subset.

The course's exact-match submission requirements and public code-link requirement are described in the [official hands-on instructions](https://huggingface.co/learn/agents-course/en/unit4/hands-on). Public claims must identify the course's 20-question GAIA validation subset rather than imply full GAIA performance.

Portfolio completion means a functioning research workflow, a usable demonstration, an honest evaluation report, and a clear explanation of design choices and limitations. Describe the owner's system-design and evaluation contribution accurately, with coding assistance acknowledged where appropriate.
