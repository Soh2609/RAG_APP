# Phase 2: Web Scraper & Documentation Crawler — Execution Plan

## Objective
Build a modular, robust web scraper and documentation crawler that crawls documentation sites, extracts clean content and links, stores raw HTML/metadata locally in `data/scraped/`, and seamlessly feeds into the Phase 1 ingestion pipeline for Qdrant indexing.

---

## Task Decomposition (Small Functional Goals)

```mermaid
flowchart TD
    T1["Sub-task 2.1: URL Normalization & Filtering\n(app/scraper/url_utils.py) ✅"] --> T2["Sub-task 2.2: Page Fetcher & Link Extractor\n(app/scraper/fetcher.py) ✅"]
    T2 --> T3["Sub-task 2.3: BFS Documentation Crawler Engine\n(app/scraper/crawler.py) ✅"]
    T3 --> T4["Sub-task 2.4: Ingestion Pipeline Bridge & CLI\n(app/scraper/pipeline.py) ✅"]
    T4 --> T5["Sub-task 2.5: End-to-End Verification & Unit Tests\n(tests/...) ✅"]
```

### Sub-task 2.1: URL Normalization & Filtering (`app/scraper/url_utils.py`)
- [x] Goal: Implement URL cleaner and validator to prevent crawl loops, deduplicate URLs, and reject non-HTML binary assets.
- [x] Functions:
  - `clean_url(url: str) -> str`: Remove URL fragments (`#section`), normalize trailing slashes, remove tracking query parameters (`utm_*`, `ref`).
  - `is_same_domain(url: str, base_domain: str) -> bool`: Strict or subdomain matching to avoid crawling external internet.
  - `is_valid_crawl_target(url: str, base_url: str, allowed_prefix: str = None) -> bool`: Check if URL is HTTP/HTTPS, matches domain, within optional path prefix, and not an image/binary/archive asset.
  - `url_to_filename(url: str) -> str`: Safe filesystem filename derivation from URL path.
- [x] Verification: 9 unit tests in `tests/test_url_utils.py` passing (100%).

### Sub-task 2.2: Page Fetcher & HTML Extractor (`app/scraper/fetcher.py`)
- [x] Goal: Robust HTTP fetcher with connection pooling, retries, headers, and clean HTML content extraction.
- [x] Functions:
  - `PageFetcher`: Class managing `requests.Session`, exponential backoff retry on transient errors (429, 502, 503), timeout enforcement.
  - `fetch_page(url: str) -> FetchResult`: Fetches page, verifies MIME type (`text/html`), handles redirects.
  - `extract_page_data(html: str, current_url: str) -> ExtractedPage`: Extracts title, outgoing resolved links, and clean text.
- [x] Verification: 4 unit tests in `tests/test_fetcher.py` passing (100%).

### Sub-task 2.3: BFS Documentation Crawler Engine (`app/scraper/crawler.py`)
- [x] Goal: Asynchronous/Breadth-First documentation crawler with limits and rate throttling.
- [x] Functions:
  - `DocumentationCrawler`:
    - Maintains a queue `collections.deque` and `visited_urls: set`.
    - Enforces `max_depth` (e.g., 3 levels deep) and `max_pages` (e.g., 50 pages).
    - Enforces polite rate limiting (`delay: float = 0.5s`).
    - Saves downloaded pages to `data/scraped/<domain>/<slug>.html`.
    - Generates a sidecar manifest: `data/scraped/<domain>/manifest.json` recording URL, title, hash, local path, status.
- [x] Verification: 2 unit tests in `tests/test_crawler.py` passing (100%).

### Sub-task 2.4: Ingestion Pipeline Bridge & CLI (`app/scraper/pipeline.py`)
- [x] Goal: Connect scraped output directly to Phase 1's `process_directory()` / `process_file()`.
- [x] Functions:
  - `scrape_and_ingest(start_url: str, max_pages: int, max_depth: int, auto_ingest: bool)`: Scrapes website and immediately feeds new documents to Qdrant.
  - CLI flags: `--url`, `--max-pages`, `--max-depth`, `--delay`, `--no-ingest`, `--wipe`.
- [x] Verification: 2 unit tests in `tests/test_pipeline.py` passing (100%).

### Sub-task 2.5: Test Suite Execution & Verification
- [x] Ran full `unittest` discovery suite across all 4 test files.
- [x] Result: **17 tests passed in 0.119s** with 0 failures and 0 errors.


---

## Phase 2.5: Unified Two-Stage Enterprise Pipeline Architecture

### Objective
Unify Web Scraping (Data Acquisition) and Vector Ingestion (Processing & Loading) into an enterprise Two-Stage Pipeline (`app/pipeline.py`) that links them logically for immediate end-to-end execution while maintaining strict decoupling for future scalability (e.g., adding S3/Google Drive connectors, swapping embedding models, or running incremental syncs).

### Sub-tasks
- [x] **Sub-task 2.5.1: Pipeline DTOs & Contracts (`app/pipeline.py`)**
  - Implement `Stage1Result`: Tracks staged directory, total files acquired, manifest path, and acquisition metadata.
  - Implement `Stage2Result`: Tracks collection name, total documents indexed, total chunks upserted, and errors.
  - Implement `PipelineResult`: Unified report aggregating both stages, total runtime, and status.
- [x] **Sub-task 2.5.2: Two-Stage Pipeline Orchestrator (`app/pipeline.py`)**
  - Stage 1 (Acquisition): Orchestrates `DocumentationCrawler` (web) or filesystem scanner (local files) into a uniform staging format.
  - Stage 2 (Vector Indexing): Consumes any staged directory via `app.ingestion.processor`, handling chunking, embedding, and Qdrant upserts.
  - Orchestrator methods:
    - `run_web_pipeline(url, max_pages, max_depth, auto_index, incremental, wipe)`
    - `run_local_pipeline(dir_path, source_type, auto_index, wipe)`
    - `run_stage2_only(staged_dir, source_type)`
- [x] **Sub-task 2.5.3: Incremental Sync via Manifest Hash-Matching**
  - Compare SHA-256 hashes of crawled files against existing Qdrant indexed records or local manifests.
  - Skip re-embedding documents whose content has not changed, saving API token costs and compute.
- [x] **Sub-task 2.5.4: Unified Enterprise CLI Interface**
  - Provide flexible command-line flags: `--url`, `--dir`, `--stage-1-only`, `--stage-2-only`, `--incremental`, `--wipe`.
- [x] **Sub-task 2.5.5: Comprehensive Unit Test Suite (`tests/test_enterprise_pipeline.py`)**
  - Test Stage 1 isolated execution.
  - Test Stage 2 isolated execution on pre-staged data.
  - Test full linked execution (Stage 1 $\to$ Stage 2).
  - Test incremental hashing logic.
  - All 21 tests across 5 test suites passing (100%).


---

## Phase 3: Vector Search & Semantic Retriever Service — Execution Plan

### Objective
Build a high-performance, filter-aware Semantic Retriever Service (`app/services/retrival/retriever.py`) that converts natural language user queries into dense vector embeddings, performs similarity search in Qdrant, applies metadata filters (e.g., by `source_type` or `source_file`), filters by relevance score threshold, and outputs structured, citation-ready context chunks for downstream LLM generation.

---

### Task Decomposition (Small Functional Goals)

```mermaid
flowchart TD
    T1["Sub-task 3.1: Retrieval Data Models & DTOs\n(RetrievedChunk, RetrievalResult)"] --> T2["Sub-task 3.2: Dynamic Metadata Filter Builder\n(build_qdrant_filter)"]
    T2 --> T3["Sub-task 3.3: Core Semantic Retriever Engine\n(SemanticRetriever, retrieve)"]
    T3 --> T4["Sub-task 3.4: CLI Query & Inspection Tool\n(app/services/retrival/retriever.py)"]
    T4 --> T5["Sub-task 3.5: Comprehensive Unit Test Suite\n(tests/test_retriever.py)"]
```

### Sub-tasks
- [x] **Sub-task 3.1: Retrieval Data Models & Contracts (`app/services/retrival/retriever.py`)**
  - Implement `RetrievedChunk`: Holds `chunk_id`, `text`, `score` (cosine similarity), `source_file`, `source_path`, `source_type`, `chunk_index`, `total_chunks`, and additional payload metadata.
  - Implement `RetrievalResult`: Unified search report containing original query, list of `RetrievedChunk` instances, `total_found`, latency in milliseconds, applied filter details, and vector dimension.
- [x] **Sub-task 3.2: Dynamic Metadata Filter Builder**
  - Implement `build_qdrant_filter()`: Generates Qdrant `models.Filter` for `source_type` (single value or list via `MatchAny`), `source_file`, or custom payload conditions.
- [x] **Sub-task 3.3: Core Semantic Retriever Engine**
  - Implement `SemanticRetriever` class with:
    - Lazy/resilient Qdrant client connection (supporting both remote cloud and local embedded storage).
    - Query embedding via `embed_query()` with dual Gemini/SentenceTransformers fallback.
    - Version-agnostic vector search (supporting `client.query_points` and fallback `client.search`).
    - Cosine similarity score thresholding (`score_threshold: Optional[float] = None`).
    - Structured latency and span tracing via Logfire.
- [x] **Sub-task 3.4: CLI Query & Inspection Interface**
  - CLI arguments: `--query`, `--top-k`, `--min-score`, `--source-type`, `--source-file`, `--collection`.
- [x] **Sub-task 3.5: Unit Test Suite & Verification (`tests/test_retriever.py`)**
  - Test query validation and empty string rejection.
  - Test filter construction (exact match and list matching).
  - Test search execution, payload mapping, and score thresholding.
  - Test integration on live/embedded Qdrant instance with synthetic indexed chunks.
  - Result: All 7 unit tests passing (28 total tests in project, 100% pass rate).

---

## Phase 4: LLM Generation Service (Groq / Llama 3.3) — Execution Plan

### Objective
Build a secure, citation-grounded Question-Answering Generation Engine (`app/services/generation/`) that integrates Phase 3's semantic retriever with Groq's high-speed Llama 3.3 model (`llama-3.3-70b-versatile`). The engine frames ingested context as untrusted data to mitigate prompt injection, generates direct answers, attaches structured provenance citations, enforces token budgeting, and short-circuits on empty retrieval to save costs.

---

### Task Decomposition (Small Functional Goals)

```mermaid
flowchart TD
    T1["Sub-task 4.1: Generation Data Models & DTOs\n(Citation, GeneratedAnswer, PromptContext)"] --> T2["Sub-task 4.2: Prompt Template & Security Guardrails\n(Untrusted Context Framing, Anti-Injection, Strict Grounding)"]
    T2 --> T3["Sub-task 4.3: Groq LLM Client & Service Layer\n(GroqGenerator, Token Budgeting, Temperature Controls)"]
    T3 --> T4["Sub-task 4.4: End-to-End RAG QA Pipeline\n(QuestionAnswerEngine: Retrieve -> Ground -> Generate -> Cite)"]
    T4 --> T5["Sub-task 4.5: Interactive CLI QA Interface\n(python -m app.services.generation.generator)"]
    T4 --> T6["Sub-task 4.6: Comprehensive Unit & Mock Test Suite\n(tests/test_generator.py)"]
```

### Sub-tasks
- [x] **Sub-task 4.1: Generation Data Models & Contracts (`app/services/generation/models.py`)**
  - Implement `Citation`: Encapsulates `source_file`, `source_path`, `source_type`, `chunk_index`, similarity `score`, and citation reference marker (`[1]`).
  - Implement `GeneratedAnswer`: Unified answer DTO containing `question`, `answer`, `citations`, `model`, `latency_ms`, token usage (`prompt_tokens`, `completion_tokens`, `total_tokens`), `grounded` boolean flag, and `to_dict()`.
- [x] **Sub-task 4.2: Prompt Template & Security Guardrails (`app/services/generation/prompts.py`)**
  - Implement system prompt framing all retrieved context as untrusted reference data with explicit instructions to ignore instructions embedded inside context blocks.
  - Enforce strict negative constraint: "If the context does not contain sufficient facts to answer the question, state: 'I don't have enough information in the provided documentation to answer this question.'"
  - Implement context budget formatter that numbers chunks `[1]`, `[2]` and truncates at `max_context_chars` (default 24,000 chars) to prevent context window overflow.
- [x] **Sub-task 4.3: Groq LLM Client & Service Layer (`app/services/generation/generator.py`)**
  - Implement `GroqGenerator` with lazy Groq client initialization, dependency injection support for unit testing, and structured Logfire spans.
  - Implement answer generation with low temperature (`temperature=0.1`) for factual determinism.
  - Implement groundedness heuristic: detects whether LLM expressed lack of information and marks `grounded=False`.
- [x] **Sub-task 4.4: End-to-End RAG QA Pipeline (`QuestionAnswerEngine`)**
  - Connect `SemanticRetriever` to `GroqGenerator`.
  - Implement short-circuit evaluation: if retrieval finds 0 chunks or filter yields empty results, immediately return ungrounded answer without consuming Groq API tokens.
- [x] **Sub-task 4.5: Interactive CLI QA Interface**
  - Provide CLI flags: `--query`, `--top-k`, `--min-score`, `--source-type`, `--source-file`, `--model`.
  - Format terminal output with markdown answer, citation reference table, and performance metrics.
- [x] **Sub-task 4.6: Unit Test Suite & Verification (`tests/test_generator.py`)**
  - Test prompt formatting and anti-injection system prompt construction.
  - Test context truncation and budgeting.
  - Test short-circuit behavior on empty retrieval.
  - Test mocked Groq API generation, token extraction, and citation mapping.
  - Test groundedness detection flag.
  - Result: All 10 unit tests passing (46 total tests across the repository, 100% pass rate).
