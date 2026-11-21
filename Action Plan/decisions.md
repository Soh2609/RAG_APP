# Architectural & Engineering Decisions Log — Phase 2: Web Scraper & Documentation Crawler

This document records the design decisions, coding patterns, trade-offs, and rationale adopted during Phase 2 development.

---

## 1. Goal Breakdown & Modular Architecture
To avoid a monolithic, fragile script, the scraper was broken down into 4 isolated, highly focused components:
- `app/scraper/url_utils.py`: Pure URL mechanics, canonicalization, and asset filtering.
- `app/scraper/fetcher.py`: HTTP transport, connection pooling, retry strategies, and BeautifulSoup extraction.
- `app/scraper/crawler.py`: Breadth-First Search (BFS) state machine, polite delays, and manifest management.
- `app/scraper/pipeline.py`: Glue bridge connecting the crawler directly to Phase 1's Qdrant vector ingestion.

---

## 2. Key Decisions & Coding Patterns

### Decision 1: Breadth-First Search (BFS) Traversal with Depth Tracking
- **The Problem**: Documentation sites (Docusaurus, GitBook, MkDocs, Sphinx) structure high-priority conceptual guides at shallow levels (`depth 1` and `depth 2`). Depth-First Search (DFS) risks following pagination links, infinite query traps, or deep changelogs before scraping the core reference documentation.
- **The Decision**: Implement BFS using `collections.deque` where every queue entry is `(url, current_depth)`.
- **Coding Pattern**: **FIFO Queue + Visited Hash Set**. Guarantees that depth $N$ is fully explored before depth $N+1$, ensuring core documentation is indexed before hitting the `max_pages` budget.

### Decision 2: Aggressive URL Canonicalization & Fragment Stripping
- **The Problem**: Documentation websites contain thousands of table-of-contents anchor tags (`#installation`, `#prerequisites`, `#api-keys`) and tracking parameters (`?utm_source=...`, `?ref=...`). Without normalization, a crawler fetches the exact same webpage dozens of times, wasting CPU, network, embedding tokens, and Qdrant storage.
- **The Decision**: Canonicalize all URLs before insertion into the BFS queue:
  - Strip `#fragments`.
  - Strip known marketing query parameters (`utm_*`, `ref`, `fbclid`).
  - Collapse duplicate slashes and normalize trailing slashes.
  - Lowercase scheme and netloc.
- **Coding Pattern**: **Functional Pipeline / Sanitizer Pattern** (`clean_url()` in `url_utils.py`).

### Decision 3: Static Asset & Binary Exclusion Filter
- **The Problem**: Web pages link to thousands of non-crawlable assets (PNG, SVG, JS, CSS, ZIP, PDF binaries). Attempting to parse these as HTML wastes bandwidth and throws parsing errors.
- **The Decision**: Maintain an explicit `EXCLUDED_EXTENSIONS` set. If a URL points to a static binary asset, it is rejected immediately before making any HTTP request.
- **Coding Pattern**: **Early Guard Clause** (`is_valid_crawl_target()`).

### Decision 4: Connection Pooling & Exponential Backoff Resiliency
- **The Problem**: Scraping multiple pages in quick succession can trigger HTTP 429 (Too Many Requests), server drops (502/503), or socket timeouts.
- **The Decision**: Utilize `requests.Session` with `urllib3.util.retry.Retry` with exponential backoff on transient errors (`[429, 500, 502, 503, 504]`), combined with an explicit per-request polite delay (`delay: float = 0.5s`).
- **Coding Pattern**: **Connection Pool + Exponential Backoff Adapter** (`PageFetcher`).

### Decision 5: Manifest-Driven Persistence (Sidecar Pattern)
- **The Problem**: If vector embedding or Qdrant fails mid-way, refetching everything from the internet wastes time and risks IP blocks.
- **The Decision**: Always persist raw cleaned HTML files into `data/scraped/<domain>/<slug>.html` alongside a central `manifest.json`.
- **Coding Pattern**: **Sidecar Manifest Pattern**. The manifest tracks `url`, `content_hash` (SHA-256), `local_file`, `depth`, and `char_count`. This enables future incremental change detection (skipping unchanged pages).

### Decision 6: Dependency Injection for High Testability
- **The Problem**: Unit tests should never depend on active external internet connections or live servers, which makes CI/CD flaky.
- **The Decision**: `DocumentationCrawler` accepts an optional `fetcher` instance. In production, it uses `PageFetcher()`; in unit tests, a mock fetcher is injected to return synthetic HTML structures instantly.
- **Coding Pattern**: **Dependency Injection (DI)**.

---

## 3. Unit Test Verification Results
All modules were thoroughly tested using Python's built-in `unittest` framework:
- `tests/test_url_utils.py`: 9 tests verifying URL cleaning, fragment stripping, domain boundaries, and filename generation.
- `tests/test_fetcher.py`: 4 tests verifying HTTP success, non-HTML content rejection, timeout handling, and HTML cleaning.
- `tests/test_crawler.py`: 2 tests verifying BFS traversal order, depth limits, page caps, and manifest generation.
- `tests/test_pipeline.py`: 2 tests verifying end-to-end integration with the Phase 1 vector ingestion processor.

**Total**: 17 tests passed in 0.119s (100% pass rate).


---

## 4. Phase 2.5: Two-Stage Decoupled Pipeline Decisions

### Decision 7: Two-Stage Pipeline Orchestrator Pattern (Decoupled Stage 1 & Stage 2)
- **The Problem**: Conflating web scraping and vector embedding into a single monolithic script creates severe architectural fragility:
  1. If embedding fails or hits rate limits, the entire crawl aborts and data is lost.
  2. If the user wants to switch embedding models or vector databases in the future, all web pages must be re-scraped from the internet, causing network delays and potential IP bans.
  3. Non-web sources (PDFs, Word docs, internal databases) cannot reuse the vector ingestion logic without duplicating code.
- **The Decision**: Formalize a strict two-stage contract in `app/pipeline.py`:
  - **Stage 1 (Acquisition / Extraction)**: Web Crawler (`DocumentationCrawler`) or file connectors acquire documents and write them into standardized staging directories (`data/scraped/<domain>`) with a `manifest.json`. Stage 1 has **zero** dependency on embeddings or vector databases.
  - **Stage 2 (Processing / Indexing)**: Ingestion Processor (`app.ingestion.processor`) reads from the staging directory, parses, chunks, embeds, and upserts into Qdrant. Stage 2 has **zero** dependency on web networking or HTTP protocols.
  - **Pipeline Orchestrator (`app/pipeline.py`)**: Acts as the mediator linking Stage 1 output directly to Stage 2 input when end-to-end execution is requested, while allowing either stage to run independently.
- **Coding Pattern**: **Orchestrator / Mediator Pattern + Data Transfer Objects (DTOs)** (`Stage1Result`, `Stage2Result`, `PipelineResult`).

### Decision 8: Manifest Hash-Based Incremental Syncing (Cost & Latency Optimization)
- **The Problem**: Web scraping documentation sites on a recurring basis (e.g. daily/weekly cron jobs) retrieves mostly identical content. Re-embedding thousands of unchanged chunks wastes API costs (Gemini / OpenAI) and vector DB writes.
- **The Decision**: Stage 1 calculates SHA-256 hashes of every page content and records them in `manifest.json`. During Stage 2, `app/pipeline.py` checks existing local audit artifacts in `processed_data/` or Qdrant points. If the content hash is identical to the previous ingestion run, the document embedding is skipped as `skipped_unchanged`.
- **Coding Pattern**: **Hash-Based Cache / Idempotent Guard Pattern**.


---

## 5. Phase 3: Vector Search & Semantic Retriever Decisions

### Decision 9: Pre-Filtering (Payload Filters) over Post-Filtering
- **The Problem**: In enterprise RAG, users often need answers scoped to specific documentation sets (e.g. only Python docs vs. TypeScript docs, or only internal policies vs. public guides). Post-filtering (retrieving top-50 globally and filtering in Python) frequently leads to 0 results if other documents dominate the vector space, and causes excessive latency.
- **The Decision**: Implement native pre-filtering directly inside Qdrant search calls using `models.Filter(must=[FieldCondition(...)])`. Qdrant's payload index evaluates filters before vector scoring, guaranteeing that all returned top-K results satisfy the user's domain/source constraints.
- **Coding Pattern**: **Dynamic Filter Builder Pattern** (`build_qdrant_filter`).

### Decision 10: Citation-First Provenance Data Model
- **The Problem**: Downstream LLM generation (Phase 4) and API responses (Phase 5) must provide transparent citations (source URL or file path, chunk index, similarity confidence) to eliminate hallucinations and build user trust.
- **The Decision**: Return a typed `RetrievedChunk` DTO containing `text`, `score`, `source_file`, `source_path`, `source_type`, `chunk_index`, and `total_chunks`. The LLM prompt builder can immediately format footnotes/citations from these structured attributes.
- **Coding Pattern**: **Data Transfer Object (DTO) + Provenance Tracking Pattern**.


### Decision 11: Decoupled Shared Database Client Layer (`app/services/retrival/qdrant.py`)
- **The Problem**: Ingestion (`processor.py`) and Retrieval (`retriever.py`) both need access to `get_qdrant_client()` and `ensure_collection()`. When `retriever.py` imported `get_qdrant_client` from `processor.py` while `processor.py` imported embeddings from `app.services.retrival`, Python threw a circular import error (`partially initialized module`).
- **The Decision**: Extract Qdrant client management into an independent low-level database client module (`app.services.retrival.qdrant`). This creates a clean Directed Acyclic Graph (DAG) of dependencies: `qdrant` $\to$ `embeddings` $\to$ `retriever` $\to$ `processor` $\to$ `pipeline`.
- **Coding Pattern**: **Service Layer Separation / Dependency Inversion**.

---

## 6. Phase 3 Unit Test Verification Results
All 7 unit tests in `tests/test_retriever.py` passed:
- Empty query rejection.
- Metadata filter construction (exact match and list matching).
- DTO serialization.
- Mocked Qdrant vector search verification.
- In-memory Qdrant integration search, ranking, and score threshold cutoff.

**Full Project Test Suite**: 28 tests across 6 test modules passed in 0.540s (100% pass rate).
