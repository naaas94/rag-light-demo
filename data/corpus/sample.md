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

## Implementation Details

### Data Flow
The system processes documents through a pipeline: Load → Chunk → Embed → Index → Retrieve → Generate.

Documents are first loaded from the filesystem using the Loader class, which supports markdown and text files. The Chunker then splits documents into smaller pieces using a sliding window approach with configurable size and overlap.

### Storage Layer
ChromaDB handles vector embeddings for semantic search, while BM25 provides lexical matching capabilities. The hybrid retrieval combines both approaches using Reciprocal Rank Fusion (RRF) to get the best of both worlds.

### Generation
The system uses Ollama for local LLM inference, supporting multiple models like Mistral, Llama2, and CodeLlama. Queries are sent with retrieved context to generate answers grounded in the indexed documents.

### Security Features
Recent improvements include HMAC-signed BM25 indices to prevent tampering, input validation via Pydantic models, resource limits to prevent memory exhaustion, and proper timeout/retry logic for external API calls.

### Configuration
The system is configurable via environment variables for timeouts, retry counts, file size limits, chunk counts, and RRF parameters. This allows fine-tuning without code changes.

## Future Enhancements
Planned improvements include async ingestion, FastAPI server mode, multi-tenancy support, and more sophisticated chunking strategies that respect semantic boundaries.
