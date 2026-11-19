# Enterprise RAG Application

An intelligent **Retrieval-Augmented Generation (RAG)** pipeline designed to ingest websites, documentation, and office files into a searchable vector database to provide accurate, context-grounded answers to user questions.

---

## 💡 What Does This Project Do?

### For Non-Technical Readers
Imagine having an expert assistant that can read hundreds of pages of documentation, web articles, PDFs, and Word documents in seconds. When you ask a question, instead of guessing or making things up, the system:
1. Searches its library for the exact relevant paragraphs.
2. Reads the relevant excerpts.
3. Gives you a direct, accurate answer with references to the original sources.

### For Technical Readers
This repository provides a modular, production-ready ingestion and retrieval pipeline:
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
├── app/
│   ├── config.py                  # Environment settings & secrets loader
│   ├── ingestion/
│   │   ├── processor.py           # Core ETL orchestrator & Qdrant indexer
│   │   ├── chunking/
│   │   │   └── splitter.py        # Semantic chunker with sliding context overlap
│   │   └── loaders/               # Multi-format file parsers
│   │       ├── html.py            # Clean HTML text extractor
│   │       ├── pdf.py             # Dual pypdf + pdfplumber engine
│   │       ├── text.py            # UTF-8 & Latin-1 text/markdown parser
│   │       └── office.py          # Word (.docx) & PowerPoint (.pptx) parser
│   └── services/
│       └── retrival/
│           └── embeddings.py      # Dual-mode embedding service (Gemini + Local)
├── data/                          # Raw input documents to ingest
├── processed_data/                # Cached JSON chunk artifacts & audit logs
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

### 3. Run Ingestion

Place documents in the `data/` directory and run:

```bash
# Ingest all files inside the data directory
python -m app.ingestion.processor --base-dir data

# Ingest a single file
python -m app.ingestion.processor --file data/sample.pdf --source-type user_guides

# Clean wipe the collection and re-index
python -m app.ingestion.processor --base-dir data --wipe
```

---

## 🗺️ Next Steps on Roadmap

- [x] **Phase 1**: Ingestion Engine & Loaders (Completed)
- [ ] **Phase 2**: Automated Web Scraper & Documentation Crawler
- [ ] **Phase 3**: Vector Search & Semantic Retriever Service
- [ ] **Phase 4**: LLM Answer Generation (Groq / Llama 3.3)
- [ ] **Phase 5**: FastAPI REST Endpoints (`/ask`, `/ingest`)
