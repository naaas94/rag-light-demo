# Runtime Optimization & Caching Review (rag-light-demo)

**Focus**: interactive **query latency** (single-user CLI now; extendable to FastAPI later)  
**Assumption**: ok to add one small caching dependency (e.g., `diskcache`)  
**Code reviewed**: `core/cli.py`, `core/store.py`, `core/retrieval.py`, `core/generation.py`, `core/observability.py`, `core/embedding.py`, `core/ingest.py`, `core/models.py`

---

## Executive summary (high-impact opportunities)

This system is already structured well for correctness and idempotency (stable doc/chunk IDs, hybrid retrieval). The biggest query-latency wins come from **reusing expensive resources** and **caching “pure” computations**.

**Top opportunities (rough priority)**:

1. **Stop re-initializing stores/indices per query** (reuse `VectorStore`, `LexicalIndex`, and a loaded BM25 in-process).
2. **Add a disk-backed cache for query embeddings and/or retrieval results** with safe invalidation tied to index versions.
3. **Reuse `ollama.Client` across generations** (keep-alive / connection reuse).
4. **Reduce prompt bloat (context budget controls)** to cut LLM latency and timeouts.
5. **Move telemetry off the hot path** (avoid serializing large outputs; async/optional flush).

---

## Current query path (where time goes)

At a high level, the query flow is:

1. **Initialize retriever** (currently per invocation):
   - `VectorStore()` → Chroma persistent client + collection
   - `LexicalIndex()` → object created; BM25 is loaded on first use
2. **Retrieve** (`Retriever.retrieve`):
   - Dense: embed query → Chroma query (disk + compute)
   - Lexical: load BM25 (pickle + HMAC verify) → BM25 score over corpus
   - Fuse: RRF merge
3. **Generate** (`Generator.generate`):
   - Build a large prompt containing full chunk texts
   - Create `ollama.Client` and call `chat`
4. **Observe**:
   - `@trace(...)` decorator logs spans (serializes inputs/outputs)
   - `telemetry.flush()` writes JSONL synchronously

### Latency budget (typical)

Your end-to-end latency is dominated by:

- **LLM generation latency** (often the largest; prompt size is a major multiplier)
- **Query embedding** (sentence-transformers encode is non-trivial CPU/GPU)
- **BM25 load** (if re-done every query due to short-lived objects)
- **Chroma query overhead** (disk access + internal compute; usually stable once warmed)

---

## Findings & optimization opportunities

### 1) Repeated initialization: `VectorStore` / `LexicalIndex` recreated per query (high impact)

**Where**: `core/cli.py` constructs `VectorStore()`, `LexicalIndex()`, and `Retriever(...)` inside every `query` command invocation.

**Why it matters**:
- Repeats Chroma client/collection setup.
- Forces the BM25 index to be loaded repeatedly because a brand-new `LexicalIndex()` has `bm25=None`.
- In any future server mode, per-request initialization would be a major throughput/latency killer.

**Recommendation**:
- Introduce a long-lived `RAGService`/`AppState` object that owns:
  - one `VectorStore` instance
  - one `LexicalIndex` instance (pre-loaded)
  - one `Retriever`
  - one `Generator` (and client)
- For CLI, reuse within process lifetime. For FastAPI, initialize once at startup.

**Expected impact**:
- Removes repeated BM25 load and reduces cold overhead; improves p50 and p95 latency.

---

### 2) BM25 load & query scoring (medium–high impact, especially for larger corpora)

**Where**:
- `Retriever.retrieve` calls `LexicalIndex.load()` if `bm25` is not loaded.
- With a fresh instance per query, this becomes “load BM25 every time”.

**Recommendation**:
- Ensure `LexicalIndex.load()` is called exactly once per process (or once per index version).
- Consider caching tokenized query results (small win).
- If the corpus is large, consider:
  - restricting BM25 search to a shortlist (e.g., by doc-level filtering), or
  - switching to a faster lexical structure for large-scale usage (out of PoC scope).

**Expected impact**:
- Eliminates repeated disk read + signature verify + pickle load per query.

---

### 3) Query embedding is recomputed every query (high impact, cacheable)

**Where**: `VectorStore.query` computes `query_embedding = self.embedder.embed([query_text])[0]`.

**Observation**:
- This is a pure computation for a given `(embed_model, normalized_query_text)`.
- Current embedder caches the model object (`Embedder._model_cache`), which is good, but does **not** cache embeddings.

**Recommendation**:
Add a cache layer:

- **In-memory LRU** (fastest, volatile; ideal for repeated queries during dev)
- **Disk-backed cache** (persist across runs; good for interactive CLI usage)

**Cache key** should include:
- embedding model name (and embedder config)
- normalized query (whitespace/case normalization)

**Expected impact**:
- Repeated queries become much faster; improves interactive experience.

---

### 4) Retrieval results can be cached (medium–high impact, must invalidate safely)

**Where**: `Retriever.retrieve` is deterministic given:
- query text
- mode (`dense|lexical|hybrid`)
- `top_k`
- the current index contents (BM25 + Chroma)

**Recommendation**:
Add a retrieval cache with conservative invalidation:

- **Cache what**:
  - **Option A (recommended first)**: cache **query embeddings** only (simpler invalidation).
  - **Option B**: cache **retrieval results** (`List[{"id","score","text","metadata"}]`) for `(query, mode, top_k, index_version)` (bigger win on repeats; requires careful invalidation).
- **Where to cache**:
  - In-process LRU (fast) + disk cache (persist across CLI runs).
- **Invalidation**:
  - Tie the cache key to an **index version** derived from BM25 and Chroma state (see “Concrete cache strategy”).

**Expected impact**:
- Repeated queries (or common queries across sessions) can skip Chroma query + BM25 scoring entirely.

---

### 5) Generation latency: prompt bloat and lack of budget controls (high impact)

**Where**: `core/generation.py` builds `context_text` by concatenating full chunk text for every retrieved chunk.

**Why it matters**:
- Prompt size increases tokenization time and model compute.
- Long prompts increase timeouts and degrade UX.

**Recommendations (practical)**:
- **Context budget**: enforce a maximum total context size (tokens if available, otherwise chars).
  - Example: `MAX_CONTEXT_CHARS=8_000` and drop lowest-ranked chunks first.
- **Per-chunk cap**: truncate each chunk to a maximum length (e.g., 1–2k chars) while retaining the `[Source: ...]` tag.
- **Deduplicate**: chunks can overlap heavily due to sliding-window chunking; remove near-duplicates by:
  - same `doc_id` + overlapping spans, or
  - Jaccard similarity of token sets (cheap) for shortlists.
- **Better context formatting**:
  - Prefer compact metadata (filename + span) and only the minimal relevant text.

**Expected impact**:
- Large reduction in LLM latency and fewer generation timeouts.

---

### 6) Ollama client created per request (medium impact)

**Where**: `Generator._generate_internal` constructs `ollama.Client(timeout=...)` on each call.

**Recommendation**:
- Create the client once in `Generator.__init__` and reuse.

**Expected impact**:
- Lower overhead and better connection reuse.

---

### 7) Telemetry on the hot path (medium impact; can become high if logs grow)

**Where**:
- `core/observability.py` `trace()` decorator stringifies inputs/outputs (potentially large).
- `cli.query` calls `telemetry.flush()` synchronously after generating.

**Recommendation**:
- Avoid logging full retrieval texts and full generated answers by default; log:
  - IDs, scores, filenames, spans, durations, model name, prompt size stats
- Make flush **optional** or **async**:
  - For CLI: flush at end is fine, but keep payload small.
  - For server: push spans to a queue and write in a background worker.

**Expected impact**:
- Reduced p95 tail latency spikes due to serialization and file I/O.

---

## Concrete cache strategy (keying + invalidation) — tailored to this repo

This section proposes a cache that is **safe-by-default** for correctness and easy to operationalize.

### A) Choose cache layers

- **L1 (in-memory)**: `functools.lru_cache` or a small LRU implementation
  - Pros: fastest
  - Cons: lost on process exit, bounded by RAM only
- **L2 (disk)**: `diskcache.Cache`
  - Pros: persists across CLI runs; easy eviction; safe concurrency for multi-process reads
  - Cons: must manage invalidation; disk I/O still slower than RAM

### B) Normalization rules (stable cache keys)

- Normalize query string:
  - strip
  - collapse internal whitespace to single spaces
  - optionally lowercase (recommended for embeddings if your embed model is case-insensitive; otherwise skip lowercasing)

### C) Index versioning (critical for retrieval-result caches)

Define an **index_version** string that changes when either lexical or vector indices change.

- **BM25 version**:
  - Use `bm25_index.pkl` **mtime** + **size** (cheap).
  - If you want stronger guarantees, compute `sha256` of the file (slower).
- **Chroma version**:
  - Use `chroma_db/chroma.sqlite3` mtime + size (cheap) and/or the directory mtime.
  - Stronger: query `collection.count()` + sqlite mtime, but count can be expensive if done frequently; cache the version for a short TTL.

Example index version string:

```text
index_version = "bm25:{mtime}:{size}|chroma:{sqlite_mtime}:{sqlite_size}"
```

### D) Cache keys (recommended)

- **Embedding cache**:
  - Key: `embed:{embed_model}:{normalized_query}`
  - Value: embedding vector
  - TTL: optional (often no TTL needed; can rely on LRU/eviction)
- **Dense retrieval cache**:
  - Key: `dense:{index_version}:{embed_model}:{top_k}:{normalized_query}`
  - Value: dense hits list
  - TTL: optional; ensure invalidation via index_version
- **Lexical retrieval cache**:
  - Key: `lex:{index_version}:{top_k}:{normalized_query}`
  - Value: lexical hits list
- **Hybrid retrieval cache**:
  - Key: `hybrid:{index_version}:{rrf_k}:{top_k}:{normalized_query}`
  - Value: fused hits list

### E) Safety + correctness guardrails

- Always include **index_version** in retrieval caches.
- Keep caches **bounded**:
  - L1: fixed maxsize
  - L2: diskcache size limit and/or culling strategy
- Don’t cache failures:
  - avoid storing exceptions/timeouts unless you add a short negative-cache TTL
- Consider a small TTL for index_version computation if it’s expensive.

### F) What not to cache (initially)

- Full generation outputs (answers) unless you also key on:
  - model name + parameters, prompt template version, and context selection logic version
  - otherwise you risk surprising staleness after ingest or prompt changes

---

## Additional runtime optimizations (secondary)

### A) Ingest-side: avoid embedding/upserting unchanged chunks (mostly for ingest throughput)

Even though this review is query-latency focused, ingest design affects query quality and store size.

**Current state**:
- Chunk IDs are stable, but ingest still embeds/upserts all chunks.

**Optimization**:
- “Upsert only missing IDs”:
  - query the store for existing IDs in batches
  - embed only missing
  - reduces time and disk churn; keeps Chroma leaner (helps queries indirectly)

### B) Chunking strategy affects query latency indirectly

- Sliding windows create heavy overlap; that:
  - increases vector DB size
  - increases similarity search noise
  - increases prompt duplication

Consider:
- chunk by paragraphs/sections first, then cap max chunk size
- store richer metadata (section headers) to improve generation without large context

---

## Benchmarking strategy (to validate improvements)

### A) What to measure

- **p50/p95 latency** for:
  - `retrieve` (dense, lexical, hybrid)
  - `generate`
  - total query time
- **Prompt size**:
  - total chars/tokens
  - chunks included
- **Cache metrics**:
  - hit rate per cache (embed, dense, lex, hybrid)
  - cache size on disk

### B) How to run (minimal harness)

- Build a fixed set of queries (10–50).
- Run each query 3–5 times:
  - first run: cold cache
  - later runs: warm cache
- Compare distributions, not just averages.

---

## Risks, pitfalls, and mitigations

- **Stale retrieval cache**: resolved by index_version-based keys.
- **Cache explosion**: mitigate with LRU, max entries, and disk size limits.
- **Incorrect normalization**: too aggressive lowercasing may change semantics (names/acronyms). Prefer whitespace normalization; apply lowercase only if consistent with your embed model behavior.
- **Security/privacy**: caches may store user queries and doc snippets locally; consider opt-out or encryption if needed.

---

## Appendix: implementation mapping (where to implement each recommendation)

This is a “follow-up PR map” that points to the natural insertion points.

### 1) Long-lived service / shared resources

- `core/cli.py`
  - Create a shared `VectorStore`, `LexicalIndex.load()`, `Retriever`, and `Generator` once per process.
- Future: `core/server.py` (or FastAPI `startup` hook) to initialize once.

### 2) Embedding cache (L1/L2)

- `core/embedding.py`
  - Add `Embedder.embed_query_cached(query_text: str) -> List[float]`
  - Add optional `diskcache` integration (behind a feature flag/env var).
- `core/store.py`
  - Update `VectorStore.query` to use the cached embedding path.

### 3) Retrieval-result cache (dense/lex/hybrid)

- `core/retrieval.py`
  - Cache at `Retriever.retrieve` boundary (best single place).
  - Key includes mode/top_k/rrf_k/index_version.
- `core/store.py`
  - Expose lightweight helpers to read index version inputs (paths/mtimes).

### 4) Prompt budget controls

- `core/generation.py`
  - Add context trimming logic before prompt creation.
  - Add env vars: `MAX_CONTEXT_CHARS`, `MAX_CHUNK_CHARS`, `DEDUP_OVERLAP_THRESHOLD`.

### 5) Reuse Ollama client

- `core/generation.py`
  - Instantiate `ollama.Client` in `Generator.__init__` and reuse in `_generate_internal`.

### 6) Telemetry off hot path

- `core/observability.py`
  - Avoid storing large `output_data`; record summaries.
  - Optional: async writer for server mode.
- `core/cli.py`
  - Make flush optional, or ensure it only logs compact span payloads.


