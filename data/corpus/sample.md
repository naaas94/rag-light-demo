
# Requirements
Local RAG System with Semantic Search and LLM Generation.

## Architecture
- **Loader**: Recursively scans folder for .md/.txt.
- **Chunker**: Recursive character split with stable IDs.
- **Store**: ChromaDB (vectors) + BM25 (lexical).
- **Retrieval**: Hybrid Search (RRF).
- **Generation**: Ollama (Mistral/Llama2).

## Philosophy
This project tests the tension between "Local Demo" and "Production Rigor".
We use structured logging (JSONL) and valid interfaces.
