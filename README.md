# Local RAG System PoC (Portfolio Grade)

> "A production-grade RAG architecture, running entirely on your localhost."

## Overview

This repository demonstrates a **Local-First RAG System** designed with systems rigor:
1.  **Stable Identity**: Documents and chunks have deterministic SHA256 IDs (idempotent ingestion).
2.  **Hybrid Retrieval**: Uses Reciprocal Rank Fusion (RRF) to combine Dense (Vector) and Lexical (BM25) signals.
3.  **Security Hardened**: HMAC-signed BM25 indices, input validation, resource limits, and timeout/retry logic.
4.  **Performance Optimized**: Multi-level caching (bounded in-memory + disk-backed) for query embeddings, persistent resource reuse, and context budget controls.
5.  **Observability**: Every request emits a structured trace (`logs/*.jsonl`).
6.  **No Cloud**: Runs 100% offline using `Ollama` and `ChromaDB` (local).

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

Note on the retrieval table:
- Snippets prefixed with `__` indicate the chunk starts mid-document (a normal artifact of sliding-window chunking).
- The `Span` column shows `start_char-end_char` offsets so you can sanity-check chunk boundaries.

**3. Evaluate**
Run the offline retrieval metric (HitRate@K) against the ground truth dataset:
```bash
python -m core.cli eval
```

**4. Cache Management**
Monitor cache performance and clear caches when needed:
```bash
# View cache statistics
python -m core.cli cache-stats

# Clear all caches (embedding cache + RAGService singleton)
python -m core.cli clear-cache
```

## Implementation Status

We explicitly distinguish between production-ready modules and PoC shortcuts:

### Implemented (Production Pattern)
*   **Stable Identity**: Documents and chunks have deterministic SHA256 IDs (idempotent ingestion).
*   **Hybrid Retrieval**: Full implementation of Reciprocal Rank Fusion (RRF) combining ChromaDB (Dense) and BM25 (Lexical).
*   **Security Hardening**: HMAC-signed BM25 indices prevent tampering, input validation via Pydantic, file size/chunk limits, and proper distance→similarity conversion.
*   **Performance Optimizations**: 
    *   **RAGService Singleton**: Long-lived service object that reuses VectorStore, LexicalIndex, and Generator instances across queries (eliminates repeated BM25 loads).
    *   **Multi-Level Embedding Cache**: L1 in-memory LRU cache + L2 disk-backed cache (via `diskcache`) for query embeddings, persisting across CLI invocations.
    *   **Persistent Ollama Client**: Connection reuse reduces overhead and improves latency.
    *   **Context Budget Controls**: Configurable limits (`MAX_CONTEXT_CHARS`, `MAX_CHUNK_CHARS`) prevent prompt bloat and generation timeouts.
*   **Resilience**: Configurable timeouts and exponential backoff retries for Ollama calls, with detailed error classification.
*   **Evaluation Harness**: functional `eval` command calculating HitRate@K using exact phrase matching against `data/eval/questions.jsonl`.
*   **Observability**: Structured JSONL logging with trace IDs for every request, with cache statistics monitoring.

### Hardcoded / Simplified
*   **Chunking Strategy**: Uses a fixed sliding window (500 chars / 50 overlap). Does not use semantic boundary detection.
*   **Embedding Model**: Defaults to `all-MiniLM-L6-v2` for local speed (configurable via code).
*   **Tokenization**: BM25 uses regex-based word tokenization (improved from naive split, but not full NLP pipeline).
*   **Evaluation Data**: rigorous but small static dataset (`data/eval/questions.jsonl`).

### Deferred (Next Steps)
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
| `EMBEDDING_CACHE_ENABLED` | `1` | Enable/disable embedding cache (set to `0` to disable) |
| `EMBEDDING_CACHE_DIR` | `.cache/embeddings` | Disk cache directory for query embeddings |
| `EMBEDDING_CACHE_SIZE_MB` | `100` | Maximum disk cache size in megabytes |
| `EMBEDDING_LRU_MAXSIZE` | `256` | In-memory LRU cache size (number of entries) |
| `MAX_CONTEXT_CHARS` | `8000` | Total context budget for prompt construction (prevents bloat) |
| `MAX_CHUNK_CHARS` | `1500` | Per-chunk truncation limit before inclusion in context |

Example:
```bash
export OLLAMA_TIMEOUT=180
export MAX_FILE_SIZE_BYTES=52428800  # 50MB
export MAX_CONTEXT_CHARS=10000  # Larger context budget
export EMBEDDING_CACHE_SIZE_MB=200  # Larger cache
python -m core.cli ingest
```

## Performance Optimizations

The system implements several runtime optimizations to reduce query latency:

*   **Resource Reuse**: The `RAGService` singleton maintains long-lived instances of VectorStore, LexicalIndex, and Generator, eliminating repeated initialization overhead (especially BM25 index loads).
*   **Query Embedding Cache**: Two-level caching strategy:
    *   **L1 (In-Memory)**: Fast bounded cache for hot queries within a session.
    *   **L2 (Disk)**: Persistent cache across CLI invocations using `diskcache`, dramatically speeding up repeated queries.
*   **Context Budget Management**: Automatic truncation of chunks and context to prevent prompt bloat, reducing LLM latency and timeout risk.
*   **Connection Reuse**: Ollama client is created once per Generator instance and reused, improving connection efficiency.

**Practical Impact**: The first query initializes resources; repeated queries typically get faster due to embedding cache hits and resource reuse. Use `python -m core.cli cache-stats` to confirm cache state on your machine.

## Project Structure

```
rag-light-demo/
├── core/
│   ├── ingest.py       # Loader & Chunker (Stable IDs, Resource Limits)
│   ├── store.py        # ChromaDB & BM25 (HMAC-signed, Improved Tokenization)
│   ├── retrieval.py    # RRF Hybrid Search (Configurable k)
│   ├── generation.py   # Ollama connection (Timeout, Retries, Context Budget)
│   ├── embedding.py    # Embedder with multi-level caching (LRU + disk)
│   ├── service.py      # RAGService singleton (resource reuse)
│   ├── models.py       # Pydantic models with validation
│   ├── cli.py          # Entry point (ingest, query, check, eval, cache-stats, clear-cache)
│   └── observability.py# Structured logging
├── data/
│   ├── corpus/         # Your documents go here
│   └── eval/           # Evaluation datasets
├── logs/               # Telemetry traces
├── .cache/             # Disk cache for embeddings (created automatically)
├── tests/              # Pytest suite
└── requirements.txt
```

## Security Notes

*   **BM25 Index Integrity**: Index files are HMAC-signed to prevent tampering. Legacy unsigned indices are automatically migrated on first load.
*   **Input Validation**: All CLI inputs are validated via Pydantic (mode, model name, question length, paths).
*   **Resource Limits**: File size and chunk count limits prevent memory exhaustion attacks.
*   **Path Traversal Protection**: Directory paths are normalized and files outside the resolved root are blocked.
*   **Cache Security**: Embedding cache keys are derived from normalized queries and model names. Cache data is stored locally and can be cleared via `clear-cache` command.

## License
MIT
