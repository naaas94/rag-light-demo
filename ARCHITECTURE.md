# Architecture & Design Decisions

## 1. The Core Tension: Prototype vs. Production
Most "RAG Demos" are 50 lines of Python glue code that fragiles easily. Production systems require:
- **Traceability**: "Why did we retrieve this chunk?"
- **Stability**: "If I ingest the same file twice, do I get duplicates?"
- **Observability**: "How long did the embedding step take?"

This PoC bridges the gap by implementing **Production Interfaces** using **Local Implementations**.

## 2. Key Design Decisions

### A. Stable IDs (Idempotency)
We do not use random UUIDs.
- `doc_id = sha1(filepath + content_hash)`
- `chunk_id = sha1(doc_id + text + offsets)`

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

## 3. Data Flow

1. **Ingest**:
   [File] -> Loader -> [Doc] -> Chunker -> [Chunks] -> Embedding -> [VectorStore] + [BM25]

2. **Query**:
   [User Query] 
      |-> [Vector Search] -> Top K
      |-> [BM25 Search] -> Top K
      |-> [RRF Fusion] -> Top Fused
   [Fused Context] -> [LLM Prompt] -> [Answer]
