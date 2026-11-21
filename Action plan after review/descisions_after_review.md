# Architectural & Engineering Decisions Log — Post-Review Hardening

> **Document Version**: 1.0  
> **Source Review**: [`code_review1.md`](file:///c:/Users/soham/OneDrive/RAG_Application/RAG_APP/code_review1.md)  
> **Scope**: Record of technical decisions, coding patterns, security mitigations, and rationale implemented during post-review remediation.

---

## 1. Summary of Review Findings & Strategic Responses

The senior backend code review in `code_review1.md` highlighted significant strengths in the project's foundational two-stage pipeline architecture, typed DTO design, and deterministic hashing. However, it revealed critical vulnerabilities and risks:
1. **Data Corruption Hazards**: Dimension mismatch (3072d vs 768d) sharing collections, and silent fallbacks masking operational degradation.
2. **Data Consistency Gaps**: Stale chunk points remaining in Qdrant when documents are updated.
3. **Security Deficits**: Absence of Server-Side Request Forgery (SSRF) controls, lack of `robots.txt` compliance, and unprotected prompt injection context.
4. **Resiliency Deficits**: Non-atomic manifest writes, missing size caps, thundering herd risks, and missing payload index error logs.

The decisions below record the specific mitigations, coding patterns, and security techniques implemented to resolve these issues.

---

## 2. P0 Blocker Mitigations & Architectural Decisions

### Decision 12: Atomic Package Normalization (`retrieval`)
- **The Problem**: The package path was spelled `app/services/retrival/` (missing an `e`). Leaving this typo creates permanent public API debt and inconsistent developer experience.
- **The Decision**: Atomically rename `app/services/retrival` to `app/services/retrieval` in a single operation, updating all 11+ import sites across loaders, pipeline, retriever, tests, and documentation.
- **Coding Pattern**: **Refactoring & Package Normalization**. Eliminates legacy typos before API surface stabilizes in Phase 4/5.

### Decision 13: Model-Partitioned Vector Collections & Hard Dimension Invariant
- **The Problem**: Google Gemini produces 3072-dimensional embeddings; SentenceTransformers (`all-mpnet-base-v2`) produces 768-dimensional embeddings. Vectors from different semantic spaces and different dimensions must never share a Qdrant collection. Recreating or sharing collections on fallback destroys existing vectors or crashes retrieval.
- **The Decision**:
  1. **Namespace Partitioning**: Dynamic collection names based on the active embedding model family:
     - Gemini: `<collection_name>_gemini_3072` (or explicitly configured collection)
     - Fallback: `<collection_name>_st_768`
  2. **Hard Dimension Invariant**: When connecting to an existing collection, verify that `collection.config.params.vectors.size == active_embedding_dim`. If mismatched, throw an explicit `DimensionMismatchError` rather than silently proceeding.
  3. **Full Lineage Payload**: Every indexed point in Qdrant records `embedding_model`, `embedding_model_name`, and `embedding_dim` in its payload.
- **Coding Pattern**: **Model-Partitioned Namespace Pattern + Hard Precondition Assertion**.
- **Security & Integrity Benefit**: Zero possibility of vector dimension poisoning or silent index corruption.

### Decision 14: Fail-Fast Safety Gates for External Fallbacks (Anti-Silent Degradation)
- **The Problem**: "Zero-downtime silent fallback" in production hides outages. If the remote Qdrant cluster fails, writing silently to local disk (`data/qdrant_storage`) leads to split-brain data and empty retrieval queries in production.
- **The Decision**: Introduce explicit safety gate flags in `app/config.py`:
  - `ALLOW_EMBEDDING_FALLBACK` (default `True` in local dev, configurable to `False` in production).
  - `QDRANT_ALLOW_LOCAL_FALLBACK` (default `False` in production, `True` only when explicitly set).
  - When a fallback occurs, emit high-visibility warnings via `logfire.warning`. If the safety flag is disabled, fail fast with a clear exception.
- **Coding Pattern**: **Fail-Fast Guard Pattern / Circuit Breaker Policy**.

### Decision 15: Idempotent Purge-Before-Upsert Lifecycle for Document Re-ingestion
- **The Problem**: Using content-hash based UUIDs (`uuid5(NAMESPACE_DNS, f"{file_hash}:{chunk_index}")`) is deterministic, but when a document's content is modified, the new hash produces new UUIDs. The previous chunks under the old hash remain in Qdrant, resulting in duplicate and conflicting search answers.
- **The Decision**: In `processor.py::process_file()`, execute an atomic scoped deletion of all existing points where `payload.source_file == current_file` before upserting the newly generated chunk batch:
  ```python
  client.delete(
      collection_name=col_name,
      points_selector=models.FilterSelector(
          filter=models.Filter(
              must=[models.FieldCondition(key="source_file", match=models.MatchValue(value=file_name))]
          )
      )
  )
  ```
- **Coding Pattern**: **Purge-Before-Upsert / Clean Slate Re-indexing Pattern**.
- **Data Integrity Benefit**: Guarantees that only the latest version of any document exists in the vector store.

### Decision 16: SSRF Mitigation via Pre-Flight DNS Resolution & IP Blocklists
- **The Problem**: Web crawlers that accept arbitrary URLs or follow links from untrusted pages are vulnerable to Server-Side Request Forgery (SSRF). Attackers can trick the crawler into fetching AWS/GCP instance metadata (`http://169.254.169.254/latest/meta-data/`), internal administration consoles (`http://127.0.0.1:8080`), or internal intranet services (`http://10.0.0.1/`).
- **The Decision**: Implement strict pre-flight URL validation in `app/scraper/url_utils.py::is_safe_url()` and enforce it in `PageFetcher`:
  1. Restrict schemes strictly to `http` and `https`.
  2. Resolve target hostname to its IP address before opening a socket.
  3. Validate the resolved IP against blocked CIDR blocks:
     - `10.0.0.0/8` (RFC 1918 Private)
     - `172.16.0.0/12` (RFC 1918 Private)
     - `192.168.0.0/16` (RFC 1918 Private)
     - `127.0.0.0/8` (Loopback)
     - `169.254.0.0/16` (Link-Local / Cloud Instance Metadata Services)
     - `::1/128` (IPv6 Loopback)
  4. Block any requests resolving to restricted networks with an explicit `SSRFSecurityError`.
- **Security Technique**: **Pre-Flight DNS Resolution & IP Boundary Enforcement**.

### Decision 17: Robots.txt Compliance & Crawl Ethics Policy
- **The Problem**: Unrestricted crawlers violate website Terms of Service, risk IP blocks, and can overload target servers.
- **The Decision**: Integrate `urllib.robotparser.RobotFileParser` into `DocumentationCrawler`.
  - Fetch and parse `<scheme>://<domain>/robots.txt` upon crawler initialization.
  - Before enqueuing or fetching any discovered URL, check `can_fetch(user_agent, url)`.
  - Extract and honor any `Crawl-delay` defined by the host.
- **Coding Pattern**: **Policy Adherence / Standard Protocol Adapter**.

---

## 3. P1 Hardening & Resilience Decisions

### Decision 18: Atomic Staging & Temp-File Replacement Pattern for Manifests
- **The Problem**: Writing JSON directly to `manifest.json` leaves the file corrupt if the process crashes mid-write (e.g., memory limit, power drop, or SIGINT).
- **The Decision**: Always write manifest updates to a sibling temporary file (`manifest.json.tmp`) and use `Path.replace()` to execute an atomic filesystem rename.
- **Coding Pattern**: **Atomic Temp-Swap Pattern**.
- **Resilience Benefit**: Read operations never encounter half-written or corrupted JSON files.

### Decision 19: Strict Configuration Management via Pydantic Settings
- **The Problem**: Inconsistent environment variable casing (`GEMINI_API_KEY`, `Qdrant_Cluster_Endpoint`, `groq_api_key`) and `os.getenv` lack type validation, returning `None` silently until deep in execution.
- **The Decision**: Migrate `app/config.py` to `pydantic_settings.BaseSettings` with `case_sensitive=False`.
  - Auto-converts and validates types at startup.
  - Provides sensible defaults (`QDRANT_COLLECTION = "enterprise_rag"`).
  - Explicitly documents all environment variables in `.env.example`.
- **Coding Pattern**: **Type-Safe Configuration / Single Source of Truth**.

### Decision 20: Resource Protection (Body & File Size Capping, Backoff Jitter)
- **The Problem**:
  1. Decompression bombs or massive HTML downloads can exhaust RAM.
  2. Concurrent workers retrying on exact exponential intervals create thundering-herd spikes on APIs.
- **The Decision**:
  1. Enforce `MAX_HTTP_BODY_BYTES = 10MB` in `fetcher.py`.
  2. Enforce `MAX_FILE_SIZE_BYTES = 50MB` in `processor.py`.
  3. Add randomized jitter to exponential backoff: `wait = 2**attempt + random.uniform(0.1, 0.9)`.
  4. Strip noisy boilerplate HTML elements (`nav`, `header`, `footer`, `aside`, `cookie-banner`).
- **Coding Pattern**: **Bounded Resource Protection + Randomized Backoff Pattern**.

---

## 4. P2/P3 Architectural & Quality Decisions

### Decision 21: Decoupled Protocol Interfaces & Domain Exception Hierarchy
- **The Problem**: Direct dependencies on concrete classes (`PageFetcher`, `GoogleGenerativeAIEmbeddings`, `QdrantClient`) hinder unit testing and prevent swapping components.
- **The Decision**:
  - Define runtime-checkable protocols in `app/core/interfaces.py`: `DocumentLoader`, `EmbeddingService`, and `VectorStore`.
  - Define custom domain exceptions in `app/core/exceptions.py`: `RAGError`, `ParseError`, `EmbeddingError`, `VectorIndexError`, `CrawlError`, `SSRFSecurityError`.
- **Coding Pattern**: **Interface Segregation / Dependency Inversion (SOLID)**.

### Decision 22: Retrieval Golden Evaluation Framework
- **The Problem**: Without quantitative measurement, chunking and embedding improvements cannot be evaluated objectively.
- **The Decision**: Establish a golden evaluation dataset in `tests/eval/golden_dataset.json` with ground-truth question-to-document mappings, evaluated with `tests/eval/evaluate_retrieval.py` measuring:
  - **Recall@K**: Proportion of relevant documents retrieved in top-K.
  - **MRR (Mean Reciprocal Rank)**: Position of the first relevant document.
- **Coding Pattern**: **Regression & Quality Assurance Benchmark**.

---

## 5. Security Techniques Summary

| Threat / Risk | Vulnerability | Implemented Mitigation Technique |
|:---|:---|:---|
| **SSRF / Cloud IMDS Leak** | Crawler accesses `169.254.169.254` or internal IPs | Pre-flight DNS resolution & IP network filter blocking RFC 1918, loopback, and link-local ranges. |
| **Index Vector Poisoning** | Incompatible vector dimensions sharing collection | Namespace-partitioned collections (`_gemini_3072`, `_st_768`) & hard dimension invariant check. |
| **Silent Outage Degradation** | Remote DB failure silently writes to ephemeral local disk | `QDRANT_ALLOW_LOCAL_FALLBACK=False` safety gate failing fast in production. |
| **Thundering Herd** | Synchronized API retries on rate limits | Exponential backoff with uniform random jitter. |
| **Process OOM / Zip Bombs** | Giant documents consuming all system memory | Pre-flight file size checks (50MB) and HTTP body size caps (10MB). |
| **File / State Corruption** | Process crash during manifest write | Atomic staging to temporary file with POSIX/Windows atomic rename. |
| **ToS / Legal Infringement** | Crawling restricted sections of sites | Integration with standard `robots.txt` parser honoring disallow rules and crawl delays. |
| **Stale / Conflicting RAG Context** | Old chunk vectors remaining after document edits | Scoped purge of previous chunks by `source_file` before upserting new chunks. |
