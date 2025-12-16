# Architecture & Design Decisions

## 1. The Core Tension: Prototype vs. Production
Most "RAG demos" are 50 lines of Python glue code that breaks easily. Production systems require:
- **Traceability**: "Why did we retrieve this chunk?"
- **Stability**: "If I ingest the same file twice, do I get duplicates?"
- **Observability**: "How long did the embedding step take?"

This PoC bridges the gap by implementing **Production Interfaces** using **Local Implementations**.

## 2. Key Design Decisions

### A. Stable IDs (Idempotency)
We do not use random UUIDs.
- `doc_id = sha256(filepath + content_hash)`
- `chunk_id = sha256(doc_id + text + offsets)`

**Benefit**: You can run `ingest` 100 times. If the file hasn't changed, the IDs are identical. No vector store pollution.

### B. Hybrid Retrieval + RRF
Pure vector search fails on specific keyword queries (e.g., acronyms, valid SKUs). Pure keyword search fails on semantic meaning.
We use **Reciprocal Rank Fusion (RRF)**:
$$ Score = \frac{1}{k + rank_{dense}} + \frac{1}{k + rank_{lexical}} $$
This method is robust and requires no tuning of "alpha" weights between scores.

### C. Observability
We avoid heavy stacks (Prometheus/Jaeger) for this demo, but we respect the **data model**:
- We emit `TraceID` and `SpanID`.
- We log to `jsonl` (structured logs).
- This allows easy ingestion into Datadog/Splunk later without code changes.

### D. Demo-Grade Security Hardening (Without Killing UX)
The threat model for a local CLI demo is still real (e.g., “clone-and-run” risks). We implemented practical guardrails:
- **Signed BM25 index**: `bm25_index.pkl` is HMAC-signed and verified on load to prevent pickle-based RCE from tampered files.
- **Path traversal protection**: ingestion normalizes the root directory and blocks files that resolve outside that root.
- **Input validation**: CLI arguments are validated via Pydantic (mode, model name format, bounds on `top_k`, non-empty queries).
- **Resource limits**: ingestion enforces file size and chunk count caps to avoid accidental memory blow-ups.

### E. Performance & Runtime Reuse
CLI tools often pay “startup tax” on every invocation. This PoC minimizes that tax:
- **RAGService singleton**: a long-lived in-memory service that owns VectorStore, LexicalIndex (BM25), and Retriever.
- **Multi-level embedding cache**: query embeddings use a bounded in-memory cache and an optional disk-backed cache (via `diskcache`) for repeated queries across runs.
- **Context budget controls**: prompt context is capped to avoid runaway generation latency (`MAX_CONTEXT_CHARS`, `MAX_CHUNK_CHARS`).

## 3. Data Flow

1. **Ingest**:
   [File] -> Loader -> [Doc] -> Chunker -> [Chunks] -> Embedding -> [VectorStore] + [BM25]

2. **Query**:
   [User Query] 
      |-> [Vector Search] -> Top K
      |-> [BM25 Search] -> Top K
      |-> [RRF Fusion] -> Top Fused
   [Fused Context] -> [LLM Prompt] -> [Answer]

## 4. Practical Debugging Aids (CLI UX)
To make retrieval results human-auditable (not just “it feels right”), the CLI surfaces:
- **Chunk spans**: `start_char-end_char` offsets so you can validate boundaries and overlap.
- **Mid-chunk marker**: snippets prefixed with `__` indicate “this chunk starts mid-document” (common with sliding windows).
