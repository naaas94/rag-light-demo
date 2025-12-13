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

**3. Check Traces**
Inspect `logs/` to see the JSONL trace of your request, including latency breakdown and retrieval scores.

## Architecture & "Tensioning"

See [ARCHITECTURE.md](ARCHITECTURE.md) for a deep dive into *why* we built it this way (Stable IDs vs Auto-increment, RRF vs Simple Cosine, etc.).

## Project Structure

```
rag-light-demo/
├── core/
│   ├── ingest.py       # Loader & Chunker (Stable IDs)
│   ├── store.py        # ChromaDB & BM25 wrappers
│   ├── retrieval.py    # RRF Hybrid Search
│   ├── generation.py   # Ollama connection
│   └── observability.py# Structured logging
├── data/
│   └── corpus/         # Your documents go here
├── logs/               # Telemetry traces
├── tests/              # Pytest suite
└── requirements.txt
```

## License
MIT
