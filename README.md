# Local RAG System PoC (Portfolio Grade)

> "A production-grade RAG architecture, running entirely on your localhost."

## Overview

This repository demonstrates a **Local-First RAG System** designed with systems rigor:
1.  **Stable Identity**: Documents and chunks have deterministic SHA1 IDs.
2.  **Hybrid Retrieval**: Uses Reciprocal Rank Fusion (RRF) to combine Dense (Vector) and Lexical (BM25) signals.
3.  **Observability**: Every request emits a structured trace (`logs/*.jsonl`).
4.  **No Cloud**: Runs 100% offline using `Ollama` and `ChromaDB` (local).

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

**3. Evaluate**
Run the offline retrieval metric (HitRate@K) against the ground truth dataset:
```bash
python -m core.cli eval
```

## Implementation Status

We explicitly distinguish between production-ready modules and PoC shortcuts:

### ✅ Implemented (Production Pattern)
*   **Stable Identity**: Documents and chunks have deterministic SHA1 IDs (idempotent ingestion).
*   **Hybrid Retrieval**: Full implementation of Reciprocal Rank Fusion (RRF) combining ChromaDB (Dense) and BM25 (Lexical).
*   **Evaluation Harness**: functional `eval` command calculating HitRate@K using exact phrase matching against `data/eval/questions.jsonl`.
*   **Observability**: Structured JSONL logging with trace IDs for every request.

### ⚠️ Hardcoded / Simplified
*   **Chunking Strategy**: Uses a fixed sliding window (500 chars / 50 overlap). Does not use semantic boundary detection.
*   **Embedding Model**: Hardcoded to `all-MiniLM-L6-v2` for local speed.
*   **Evaluation Data**: rigorous but small static dataset (`data/eval/questions.jsonl`).

### 🚧 Deferred (Next Steps)
*   **FastAPI / HTTP Server**: The `serve` command is currently a stub.
*   **Async Ingestion**: Ingestion is synchronous; a production version would use a Celery/Queuing system.
*   **Multi-Tenancy**: The current database assumes a single tenant context.

## Project Structure

```
rag-light-demo/
├── core/
│   ├── ingest.py       # Loader & Chunker (Stable IDs)
│   ├── store.py        # ChromaDB & BM25 wrappers
│   ├── retrieval.py    # RRF Hybrid Search
│   ├── generation.py   # Ollama connection
│   ├── cli.py          # Entry point (ingest, query, check, eval)
│   └── observability.py# Structured logging
├── data/
│   ├── corpus/         # Your documents go here
│   └── eval/           # Evaluation datasets
├── logs/               # Telemetry traces
├── tests/              # Pytest suite
└── requirements.txt
```

## License
MIT
