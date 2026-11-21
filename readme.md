# Enterprise RAG Application

An intelligent **Retrieval-Augmented Generation (RAG)** pipeline designed to crawl documentation websites and ingest multi-format files into a searchable vector database to provide accurate, context-grounded answers to user questions.

---

## 💡 What Does This Project Do?

### For Non-Technical Readers
Imagine having an expert assistant that can automatically browse and read an entire documentation website (or hundreds of pages of PDFs, Word documents, and text files) in seconds. When you ask a question, instead of guessing or hallucinating, the system:
1. Searches its library for the exact relevant paragraphs.
2. Reads the relevant excerpts.
3. Gives you a direct, accurate answer with references to the original sources and web URLs.

### For Technical Readers
This repository provides a modular, production-ready ingestion, crawling, and retrieval pipeline:
- **Automated Web & Docs Crawler**: Breadth-First Search (BFS) crawler with canonical URL normalization, static asset filtering, polite rate limiting, and sidecar `manifest.json` generation.
- **Multi-Format Ingestion**: Parsers for HTML, PDF, Word (`.docx`), PowerPoint (`.pptx`), and plain text/markdown.
- **Semantic Text Chunker**: Overlap-aware recursive paragraph splitting preserving contextual continuity.
- **Dual-Mode Embedding Engine**: Primary Google Gemini (`gemini-embedding-2-preview`, 3072-dim) with automatic, zero-downtime fallback to local `sentence-transformers/all-mpnet-base-v2` (768-dim).
- **Resilient Vector Storage**: Qdrant vector database integration with automatic local embedded fallback (`data/qdrant_storage`) if cloud clusters are offline or unconfigured.
- **Idempotent Ingestion**: SHA-256 content hashing and deterministic UUIDs (`uuid5`) to prevent duplicate vectors.
- **Observability**: Built-in structured spans and logging via Logfire.

---

## 📁 Repository Structure

```text
RAG_APP/
├── Action Plan/                   # Strategic engineering plans & decisions logs
│   ├── plan.md                    # Phase-by-phase execution plan & task tracker
│   └── decisions.md               # Architectural decisions, coding patterns & rationale
├── app/
│   ├── config.py                  # Environment settings & secrets loader
│   ├── pipeline.py                # Unified Two-Stage Enterprise Pipeline orchestrator
│   ├── ingestion/
│   │   ├── processor.py           # Core ETL orchestrator & Qdrant indexer
│   │   ├── chunking/
│   │   │   └── splitter.py        # Semantic chunker with sliding context overlap
│   │   └── loaders/               # Multi-format file parsers (HTML, PDF, Text, Office)
│   ├── scraper/
│   │   ├── url_utils.py           # Canonical URL cleaning & asset filtering
│   │   ├── fetcher.py             # Connection-pooled HTTP fetcher & HTML extractor
│   │   ├── crawler.py             # BFS documentation crawler engine & manifest writer
│   │   └── pipeline.py            # Scraper-to-Qdrant bridge
│   └── services/
│       └── retrival/
│           ├── __init__.py        # Clean package interface for retrieval & embeddings
│           ├── qdrant.py          # Centralized Qdrant client & collection manager
│           ├── embeddings.py      # Dual-mode embedding service (Gemini + Local)
│           └── retriever.py       # High-performance semantic retriever & pre-filter engine
├── data/                          # Input data directory
│   └── scraped/                   # Crawled HTML pages & manifests per domain
├── processed_data/                # Cached JSON chunk artifacts & audit logs
├── tests/                         # Comprehensive unit test suite (28 tests, 100% pass)
│   ├── test_url_utils.py          # URL cleaning & validation unit tests
│   ├── test_fetcher.py            # HTTP fetcher & HTML extraction unit tests
│   ├── test_crawler.py            # BFS crawler & manifest unit tests
│   ├── test_pipeline.py           # Scrape-and-ingest bridge unit tests
│   ├── test_enterprise_pipeline.py# Decoupled Two-Stage Pipeline unit tests
│   └── test_retriever.py          # Vector search, metadata filtering & threshold tests
├── main.py                        # Application entry point
├── requirements.txt               # Project dependencies
└── .env                           # Environment variables (API keys)
```

---

## 🚀 Quickstart Guide

### 1. Environment Setup
Install dependencies into a virtual environment:

```bash
# Activate your environment
.venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure Credentials (`.env`)
Create or edit your `.env` file in the project root:

```env
# Gemini Embeddings
GEMINI_API_KEY=your_gemini_api_key

# Qdrant Vector DB (Cloud or leave blank for automatic local storage)
Qdrant_Cluster_Endpoint=https://your-cluster-url.qdrant.io
Qdrant_Api_Key=your_qdrant_api_key

# Groq LLM (for answer generation)
groq_api_key=your_groq_api_key
```

### 3. Run Unified Two-Stage Enterprise Pipeline
The orchestrator at `app/pipeline.py` links Stage 1 (Acquisition) and Stage 2 (Vector Indexing) seamlessly while supporting decoupled execution and incremental change-detection:

```bash
# 1. Full End-to-End: Crawl documentation website and index vectors into Qdrant
python -m app.pipeline --url https://docs.example.com --max-pages 20

# 2. Incremental Sync: Crawl and only embed new or modified pages (skips unchanged content)
python -m app.pipeline --url https://docs.example.com --incremental

# 3. Stage 1 Only: Crawl and stage HTML + manifest without vector indexing
python -m app.pipeline --url https://docs.example.com --stage-1-only

# 4. Stage 2 Only: Index an existing staged folder into Qdrant without scraping
python -m app.pipeline --dir data/scraped/docs.example.com --stage-2-only

# 5. Local Documents: Ingest a folder of local PDFs, DOCX, and text files
python -m app.pipeline --dir data --source-type enterprise_manuals
```

### 4. Semantic Vector Search & Retrieval
Query your indexed vector database using the high-performance Semantic Retriever CLI with optional pre-filtering and score thresholding:

```bash
# 1. Basic semantic query (top 3 chunks)
python -m app.services.retrival.retriever --query "How does the text chunker work?" --top-k 3

# 2. Query with metadata pre-filtering (e.g. only web documentation)
python -m app.services.retrival.retriever --query "What is the retry policy?" --source-type web_documentation

# 3. Query with minimum similarity confidence threshold
python -m app.services.retrival.retriever --query "How to configure embeddings?" --min-score 0.70
```

### 5. Run Unit Tests
Run the entire unit test suite (100% pass across 28 tests):

```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## 🗺️ Next Steps on Roadmap

- [x] **Phase 1**: Ingestion Engine & Loaders (Completed)
- [x] **Phase 2**: Automated Web Scraper & Documentation Crawler (Completed)
- [x] **Phase 3**: Vector Search & Semantic Retriever Service (Completed)
- [ ] **Phase 4**: LLM Answer Generation (Groq / Llama 3.3)
- [ ] **Phase 5**: FastAPI REST Endpoints (`/ask`, `/ingest`)
