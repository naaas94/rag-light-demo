# Local RAG System PoC (Portfolio Grade)

> "A production-grade RAG architecture, running entirely on your localhost."

## Overview

This repository demonstrates a **Local-First RAG System** designed with systems rigor:
1.  **Stable Identity**: Documents and chunks have deterministic SHA256 IDs (idempotent ingestion).
2.  **Hybrid Retrieval**: Uses Reciprocal Rank Fusion (RRF) to combine Dense (Vector) and Lexical (BM25) signals.
3.  **Security Hardened**: HMAC-signed BM25 indices, input validation, resource limits, and timeout/retry logic.
4.  **Observability**: Every request emits a structured trace (`logs/*.jsonl`).
5.  **No Cloud**: Runs 100% offline using `Ollama` and `ChromaDB` (local).

## Quick Start (Plug & Play)

### Prerequisites
1.  Install [Ollama](https://ollama.ai) and run `ollama serve`.
2.  Pull the generation model:
    ```bash
    ollama pull mistral
    ```
3.  Python 3.10+ installed.

### Installation

```bash
git clone https://github.com/your-username/rag-light-demo.git
cd rag-light-demo

# Install dependencies
pip install -r requirements.txt
```

### Usage

**0. Sanity Check**
Verify external dependencies (Ollama) and internal state:
```bash
python -m core.cli check
```

**1. Ingest Documents**
Place your `.md` or `.txt` files in `data/corpus` (a sample is provided).
```bash
python -m core.cli ingest
```
*This will create a `chroma_db` folder and `bm25_index.pkl`.*

**2. Query**
Ask a question about your documents:
```bash
python -m core.cli query "What is the architecture?"
```

Options:
- `--top-k N`: Number of chunks to retrieve (default: 5)
- `--mode {dense|lexical|hybrid}`: Retrieval mode (default: hybrid)
- `--model MODEL`: Ollama model name (default: mistral)

**3. Evaluate**
Run the offline retrieval metric (HitRate@K) against the ground truth dataset:
```bash
python -m core.cli eval
```

## Implementation Status

We explicitly distinguish between production-ready modules and PoC shortcuts:

### ✅ Implemented (Production Pattern)
*   **Stable Identity**: Documents and chunks have deterministic SHA256 IDs (idempotent ingestion).
*   **Hybrid Retrieval**: Full implementation of Reciprocal Rank Fusion (RRF) combining ChromaDB (Dense) and BM25 (Lexical).
*   **Security Hardening**: HMAC-signed BM25 indices prevent tampering, input validation via Pydantic, file size/chunk limits, and proper distance→similarity conversion.
*   **Resilience**: Configurable timeouts and exponential backoff retries for Ollama calls, with detailed error classification.
*   **Evaluation Harness**: functional `eval` command calculating HitRate@K using exact phrase matching against `data/eval/questions.jsonl`.
*   **Observability**: Structured JSONL logging with trace IDs for every request.

### ⚠️ Hardcoded / Simplified
*   **Chunking Strategy**: Uses a fixed sliding window (500 chars / 50 overlap). Does not use semantic boundary detection.
*   **Embedding Model**: Defaults to `all-MiniLM-L6-v2` for local speed (configurable via code).
*   **Tokenization**: BM25 uses regex-based word tokenization (improved from naive split, but not full NLP pipeline).
*   **Evaluation Data**: rigorous but small static dataset (`data/eval/questions.jsonl`).

### 🚧 Deferred (Next Steps)
*   **FastAPI / HTTP Server**: The `serve` command is currently a stub.
*   **Async Ingestion**: Ingestion is synchronous; a production version would use a Celery/Queuing system.
*   **Multi-Tenancy**: The current database assumes a single tenant context.

## Configuration

The system supports environment variables for fine-tuning:

| Variable | Default | Description |
|----------|---------|-------------|
| `BM25_SECRET_KEY` | `rag-demo-secret-key...` | HMAC key for signing BM25 indices (change in production) |
| `OLLAMA_TIMEOUT` | `120` | Request timeout in seconds |
| `OLLAMA_MAX_RETRIES` | `3` | Number of retry attempts with exponential backoff |
| `MAX_FILE_SIZE_BYTES` | `10485760` | Maximum file size for ingestion (10MB) |
| `MAX_CHUNK_COUNT` | `10000` | Maximum chunks per ingestion run |
| `RRF_K` | `60` | RRF fusion k parameter (standard value) |

Example:
```bash
export OLLAMA_TIMEOUT=180
export MAX_FILE_SIZE_BYTES=52428800  # 50MB
python -m core.cli ingest
```

## Project Structure

```
rag-light-demo/
├── core/
│   ├── ingest.py       # Loader & Chunker (Stable IDs, Resource Limits)
│   ├── store.py        # ChromaDB & BM25 (HMAC-signed, Improved Tokenization)
│   ├── retrieval.py    # RRF Hybrid Search (Configurable k)
│   ├── generation.py   # Ollama connection (Timeout, Retries)
│   ├── models.py       # Pydantic models with validation
│   ├── cli.py          # Entry point (ingest, query, check, eval)
│   └── observability.py# Structured logging
├── data/
│   ├── corpus/         # Your documents go here
│   └── eval/           # Evaluation datasets
├── logs/               # Telemetry traces
├── tests/              # Pytest suite
└── requirements.txt
```

## Security Notes

*   **BM25 Index Integrity**: Index files are HMAC-signed to prevent tampering. Legacy unsigned indices are automatically migrated on first load.
*   **Input Validation**: All CLI inputs are validated via Pydantic (mode, model name, question length, paths).
*   **Resource Limits**: File size and chunk count limits prevent memory exhaustion attacks.
*   **Path Traversal Protection**: Directory paths are normalized and files outside the resolved root are blocked.

## License
MIT
