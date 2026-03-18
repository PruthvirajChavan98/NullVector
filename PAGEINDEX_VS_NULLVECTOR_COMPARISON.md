# PageIndex vs NullVector: Engineering Comparison

## Short Verdict

PageIndex and NullVector overlap in one important way: both are trying to make long-document retrieval work through structure instead of a traditional vector database. Both center the document tree as the retrieval primitive, and both use LLMs to improve navigation or summarization over that structure.

The engineering shape is very different, though. In the local repos inspected here, PageIndex is a compact, OpenAI-centric package optimized for fast experimentation, notebook usage, and direct tree generation from PDFs or Markdown. NullVector is a much broader framework optimized for deterministic ingestion, typed contracts, explicit artifacts, auditable LLM boundaries, multiple storage backends, and downstream retrieval/export workflows.

The simplest way to think about the difference is:

- PageIndex is closer to a focused tree-index generator with notebook and tutorial workflows.
- NullVector is closer to a document-processing platform with ingestion, tree synthesis, retrieval artifacts, storage, and typed gateway/runtime boundaries.

## Repo Snapshot

These counts are local workspace observations, not claims about every upstream revision.

| Signal | PageIndex | NullVector |
|---|---:|---:|
| Python files | 5 | 128 |
| Approx. Python lines | ~2,330 | ~23,307 |
| Python test files found | 0 | 38 |
| Notebooks | 4 | 45 |
| Main package surface | `pageindex/` | `src/nullvector/` |
| Primary entrypoint style | CLI + notebooks | Framework modules + notebooks + scripts |

## Side-by-Side Comparison

| Dimension | PageIndex | NullVector |
|---|---|---|
| Primary goal | Generate a PageIndex tree and enable reasoning-based document retrieval workflows. The README frames it as vectorless, reasoning-based RAG. | Build deterministic, verifiable document hierarchies and retrieval artifacts from large technical PDFs. |
| Scope | Compact package centered on tree construction from PDF or Markdown plus tutorial retrieval patterns. | Broader framework with ingestion, projection, tree synthesis, semantic services, retrieval corpus building, LLM gateways, storage, observability, and exporters. |
| Architecture shape | Most behavior is concentrated in `pageindex/page_index.py`, `pageindex/page_index_md.py`, `pageindex/utils.py`, and `run_pageindex.py`. | Behavior is split across explicit subsystems such as `ingest`, `tree`, `semantic`, `retrieval`, `storage`, `llm`, `domain`, and `observability`. |
| Ingestion/parsing model | Direct PDF or Markdown processing. PDF flow is driven from the CLI and helper functions; Markdown is handled by a dedicated converter. | Deterministic-first acquisition pipeline with explicit manifests, canonical ledgers, text substrates, projections, and typed run artifacts. |
| Tree/index generation | Tree generation and cleanup live close to prompt logic and runtime helpers; LLM calls are embedded in the package runtime. | Tree generation is a staged pipeline with typed requests/settings, deterministic strategies, verification, optional repair, optional decomposition, and optional summarization. |
| Retrieval/query path | Open-source repo mainly exposes tutorials for tree search and document-search strategies rather than a large retrieval runtime package. | Includes retrieval corpus construction, typed retrieval manifests/evidence models, and export surfaces for downstream integrations. |
| LLM integration model | OpenAI wrappers in utility helpers with prompt-first orchestration, retry loops, and JSON extraction cleanup. | Structured gateway with typed request/response contracts, adapters, retry policy, audit persistence, typed failures, and explicit assurance modes. |
| Storage/artifact model | Primarily local file outputs such as `results/*.json` and `logs/*.json`. | Artifact-oriented manifests and run-scoped stores, with both filesystem and PostgreSQL backends. |
| Typing/contracts | Lightly typed Python, dictionary-heavy tree objects, and utility-style data manipulation. | Strong Pydantic domain contracts for acquisition, tree, retrieval, gateway, and storage boundaries. |
| Testing/maturity signals | Tutorial-heavy, notebook-friendly, very small code surface, and no local Python test files found in the inspected repo. | Larger module surface, committed fixtures, explicit validation flows, and a substantial local automated test suite. |
| Local developer workflow | `pip install -r requirements.txt`, set `CHATGPT_API_KEY`, run `python3 run_pageindex.py ...`, then follow notebooks/tutorials. | `uv sync --extra dev`, typed validation/test commands, notebooks for deterministic verification, and backend-aware runtime validation. |
| Best fit | Fast experimentation, lightweight tree indexing, direct notebook exploration, and teams comfortable with prompt-centric runtime logic. | Verifiable pipelines, structured artifacts, backend flexibility, typed interfaces, and teams building an extendable document-processing stack. |

## 1. Product Thesis

### PageIndex

PageIndex is explicitly positioned, in its README, as a "vectorless, reasoning-based RAG" system built around a document tree. The central idea is that the model should reason over the tree structure instead of retrieving semantically similar chunks from a vector store. That product thesis is visible in the open-source repo:

- the CLI generates a tree structure JSON from a PDF or Markdown file
- the tutorials focus on tree search and document search strategies
- the package surface is intentionally small

In other words, PageIndex is not trying to be a general document-processing framework in this repo. It is trying to make the tree itself the main retrieval object.

### NullVector

NullVector’s README describes a different center of gravity. It presents the project as a CPU-first document hierarchy framework for deterministic ingestion into verifiable hierarchical JSON artifacts. The tree is still central, but it is one stage inside a bigger system:

- acquisition and parsing
- canonical ledger and text substrate generation
- deterministic tree synthesis and verification
- optional LLM repair/summarization
- retrieval corpus building
- storage and export paths

So while both projects care about hierarchical document structure, PageIndex starts from "reasoning-based retrieval over a tree," while NullVector starts from "deterministic document processing that can produce a trustworthy tree and retrieval artifacts."

## 2. Architecture and Code Organization

### PageIndex

The PageIndex repo is very concentrated:

- `run_pageindex.py` is the main CLI entrypoint
- `pageindex/page_index.py` contains the majority of PDF tree-generation logic
- `pageindex/page_index_md.py` contains the Markdown-to-tree pipeline
- `pageindex/utils.py` contains OpenAI calls, token counting, JSON extraction, PDF helpers, and general tree utilities
- `pageindex/__init__.py` re-exports the small public surface

That concentration has a clear upside: the project is easy to grasp quickly. A single engineer can understand the main control flow without traversing many modules.

The tradeoff is that concerns are mixed together more aggressively:

- prompt construction
- OpenAI transport calls
- retry logic
- JSON cleanup
- tree mutation
- PDF processing helpers

This is efficient for rapid iteration, but it makes the runtime boundary less strict.

### NullVector

NullVector is deliberately decomposed. The repo shows subsystem boundaries instead of one dominant module:

- `src/nullvector/ingest/` handles acquisition and canonical document artifacts
- `src/nullvector/tree/` handles hierarchy synthesis, TOC work, verification, repair, decomposition, and orchestration
- `src/nullvector/semantic/` handles tokenizer-backed semantic services
- `src/nullvector/retrieval/` builds retrieval corpora and manifests from acquisition and tree artifacts
- `src/nullvector/storage/` provides filesystem and PostgreSQL-backed storage
- `src/nullvector/llm/` provides typed structured gateway behavior
- `src/nullvector/domain/` defines typed contracts
- `src/nullvector/observability/` provides event/logging utilities

This is a much heavier engineering shape than PageIndex, but it gives NullVector cleaner subsystem boundaries and clearer extension points.

## 3. Pipeline Differences

### PageIndex pipeline

The PageIndex pipeline is direct:

1. Accept a PDF path or Markdown path via `run_pageindex.py`.
2. Build a tree using package helpers.
3. Optionally add node IDs, summaries, descriptions, and node text.
4. Save the resulting structure JSON under `results/`.

For Markdown, `page_index_md.py` extracts headers, assembles node text, builds a nested structure, and optionally summarizes/thins nodes.

For PDF, `page_index.py` handles TOC detection, TOC extraction, title appearance checks, page-index extraction, and related tree-building logic. The LLM is tightly embedded in that process rather than isolated behind a strict service boundary.

This design is straightforward and useful when the desired artifact is primarily "a tree structure for a document."

### NullVector pipeline

NullVector’s pipeline is broader and more staged:

1. Acquire a document into typed acquisition artifacts.
2. Build a canonical ledger and text substrate.
3. Project those artifacts into a tree-synthesis view.
4. Run deterministic hierarchy synthesis and verification.
5. Optionally use bounded LLM repair, decomposition, verification assistance, and summarization.
6. Persist tree manifests, node cards, summaries, and related artifacts.
7. Build retrieval corpora from acquisition + tree outputs.

That staging matters. NullVector is not just building a tree; it is producing a chain of reusable artifacts that later steps can trust, reload, and validate.

## 4. LLM Boundary and Reliability Model

### PageIndex

PageIndex uses a prompt-first, helper-driven LLM model:

- `ChatGPT_API`, `ChatGPT_API_async`, and `ChatGPT_API_with_finish_reason` in `pageindex/utils.py`
- fixed retry loops
- dictionary/json-based parsing
- `extract_json()` cleanup to recover JSON from model output

This is pragmatic and fast to work with, but the reliability contract is lighter:

- runtime payloads are dictionary-heavy
- JSON extraction is tolerant and cleanup-based
- the transport boundary is OpenAI-specific in the inspected repo
- failure handling is serviceable but not strongly typed end-to-end

That is not inherently wrong. It just reflects a different engineering priority: optimize for iteration speed and direct capability rather than a strict framework-owned contract boundary.

### NullVector

NullVector takes the opposite approach. The gateway is a first-class subsystem:

- typed gateway request/response models
- structured output modes
- adapter boundaries for providers/transports
- typed failure envelopes and exceptions
- audit persistence
- explicit retry logic owned by the framework

This is materially closer to "LLM as a governed subsystem" than "LLM helper functions inside the main runtime." It also makes NullVector’s LLM behavior more auditable and easier to reason about in a multi-stage document pipeline.

One practical consequence is that PageIndex is simpler to wire up if OpenAI is your default assumption, while NullVector is better suited when LLM behavior needs to be explicit, typed, and operationally inspectable.

## 5. Storage, Artifacts, and Operability

### PageIndex

PageIndex primarily writes local outputs:

- `results/*.json` tree structures
- `logs/*.json` runtime artifacts

That is enough for single-user or notebook-oriented workflows, and it keeps the operational model simple.

What it does not try to provide in this repo is a storage abstraction for multiple backends, typed run reservation/completion semantics, or manifest-oriented reloading across stages.

### NullVector

NullVector is much more explicit about artifact lifecycle:

- acquisition manifests
- tree manifests
- retrieval manifests
- canonical ledgers and text substrates
- audit records
- run-scoped artifact references

It also has shared storage abstractions plus a PostgreSQL-backed implementation. That signals a different use case: NullVector expects artifacts to survive beyond a single notebook session and to be consumed by later stages or different runtimes.

So if the question is "can I quickly generate and inspect a tree," PageIndex’s file model is enough. If the question is "can I build a repeatable artifact pipeline that different components can reload and verify," NullVector is much stronger.

## 6. Maturity Signals

This section is intentionally about repo-local engineering signals, not popularity or external benchmarks.

### PageIndex strengths

- very small code surface
- easy to inspect end-to-end
- notebook and tutorial workflow is prominent
- clear CLI entrypoint
- minimal dependency stack

These are real strengths. Small surface area lowers onboarding cost and reduces framework drag.

### PageIndex limits visible in the repo

- no local Python test files found in the inspected tree
- core logic is centralized in a few modules, which increases coupling
- OpenAI integration is built into runtime helpers rather than isolated behind a strict provider boundary
- retrieval behavior in the open-source repo is documented more through tutorials than through a broad internal retrieval subsystem

### NullVector strengths

- large typed domain surface
- clear subsystem decomposition
- automated tests and fixtures
- explicit storage abstractions
- explicit retrieval/build/export packages
- explicit gateway and observability boundaries

### NullVector limits

- significantly higher complexity
- more concepts to learn before becoming productive
- more implementation overhead for simple one-off use cases
- stronger framework shape means slower experimentation if the goal is only "generate a tree fast"

In short, PageIndex looks lighter and more opinionated. NullVector looks heavier and more infrastructural.

## 7. When To Choose Which

### Choose PageIndex when

- you want to prototype tree-based vectorless retrieval quickly
- your workflow is notebook- and prompt-driven
- you are comfortable with a compact OpenAI-centric runtime
- you care more about speed of experimentation than typed platform boundaries
- your primary deliverable is the tree plus tutorial-style retrieval workflows

### Choose NullVector when

- you need deterministic-first ingestion and verification
- you want typed artifacts and explicit manifests between stages
- you need storage flexibility beyond local JSON files
- you care about auditable LLM boundaries and structured failure handling
- you expect the system to grow into a broader document-processing stack

## Bottom Line

PageIndex and NullVector are adjacent, not identical.

PageIndex is the better fit if the team wants a small, approachable package for generating document trees and experimenting with reasoning-based retrieval patterns quickly.

NullVector is the better fit if the team wants a framework-quality document pipeline with stronger guarantees around contracts, artifacts, storage, validation, and operational behavior.

The key mistake would be comparing them as if they were the same kind of repo. They are solving overlapping problems, but at different system layers and with different engineering priorities.

## Recommendation Matrix

| Scenario | Better Fit | Why |
|---|---|---|
| Quick proof-of-concept for tree-based vectorless retrieval | PageIndex | Smaller surface, faster onboarding, direct CLI/notebook path |
| Production-minded document pipeline with staged artifacts | NullVector | Stronger typing, manifest lifecycle, storage backends, subsystem boundaries |
| Minimal package for PDF/Markdown to tree conversion | PageIndex | Core repo is tightly focused on tree generation |
| Extensible framework for ingestion, verification, retrieval, and export | NullVector | Broader architecture already exists in the codebase |
| Strictly governed LLM runtime with typed failures and audits | NullVector | Gateway subsystem is explicit and framework-owned |
| Tutorial-led adoption by researchers or prompt engineers | PageIndex | Repo shape is simpler and tutorial-heavy |

## Appendix: Evidence Used

### PageIndex sources inspected

- `/home/pruthvi/projects/github/PageIndex/README.md`
- `/home/pruthvi/projects/github/PageIndex/requirements.txt`
- `/home/pruthvi/projects/github/PageIndex/run_pageindex.py`
- `/home/pruthvi/projects/github/PageIndex/pageindex/__init__.py`
- `/home/pruthvi/projects/github/PageIndex/pageindex/page_index.py`
- `/home/pruthvi/projects/github/PageIndex/pageindex/page_index_md.py`
- `/home/pruthvi/projects/github/PageIndex/pageindex/utils.py`
- `/home/pruthvi/projects/github/PageIndex/pageindex/config.yaml`
- `/home/pruthvi/projects/github/PageIndex/cookbook/README.md`
- `/home/pruthvi/projects/github/PageIndex/tutorials/doc-search/README.md`
- `/home/pruthvi/projects/github/PageIndex/tutorials/tree-search/README.md`

### NullVector sources inspected

- `/home/pruthvi/projects/NullVector/README.md`
- `/home/pruthvi/projects/NullVector/src/nullvector/tree/service.py`
- `/home/pruthvi/projects/NullVector/src/nullvector/domain/tree.py`
- `/home/pruthvi/projects/NullVector/src/nullvector/llm/service.py`
- `/home/pruthvi/projects/NullVector/src/nullvector/retrieval/build.py`
- `/home/pruthvi/projects/NullVector/src/nullvector/storage/postgres.py`
- subsystem directories under `/home/pruthvi/projects/NullVector/src/nullvector/`

### Notes on evidence quality

- Product positioning statements for PageIndex are taken from its README and tutorials.
- Architectural and implementation statements are based on the local code inspected above.
- Repo-size counts are workspace observations gathered from the local checkout and should not be treated as timeless upstream facts.
- External service, benchmark, MCP, API, or hosted-product claims were intentionally not used as decision-driving evidence here unless they appeared as README-stated context.
