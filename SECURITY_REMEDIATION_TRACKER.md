# Security & Architecture Remediation Tracker

## Executive Summary

This document tracks the remediation status of all issues identified in `SECURITY_ARCHITECTURE_REVIEW.md`. It is scoped for a **CLI demo** (`make query Q="xxx"`) that may evolve into an MVP.

| Category | Fixed | Partial | Outstanding | Total |
|----------|-------|---------|-------------|-------|
| Security (1.x) | 1 | 0 | 4 | 5 |
| Architecture (2.x) | 1 | 0 | 3 | 4 |
| Performance (3.x) | 1 | 1 | 4 | 6 |
| Scaling (4.x) | 0 | 0 | 5 | 5 |
| Functionality (5.x) | 0 | 1 | 4 | 5 |
| Data Integrity (6.x) | 0 | 0 | 3 | 3 |
| Code Quality (7.x) | 0 | 0 | 3 | 3 |
| Testing (8.x) | 0 | 0 | 2 | 2 |
| Deployment (9.x) | 0 | 0 | 3 | 3 |
| **TOTAL** | **3** | **2** | **31** | **36** |

**Overall Progress**: 3 fixed, 2 partial, 31 outstanding (14% resolved)

---

## Status Legend

| Badge | Meaning |
|-------|---------|
| ✅ FIXED | Issue resolved, verified in code |
| 🔶 PARTIAL | Partially addressed, needs completion |
| ❌ OUTSTANDING | Not yet addressed |
| 🎯 DEMO-CRITICAL | Must fix for demo quality |
| 📋 DEMO-RECOMMENDED | Should fix for polish |
| 🔮 MVP-DEFERRED | Can defer to MVP phase |

---

## 1. SECURITY VULNERABILITIES

### 1.1 Path Traversal Vulnerability ✅ FIXED

**Original Issue**: `core/ingest.py:16` - `glob.glob()` with user-controlled directory without validation.

**Current Status**: FIXED

**Evidence**: `core/ingest.py` lines 25-50 now contain:
```python
# Path traversal protection: validate and normalize directory path
resolved_dir = os.path.abspath(os.path.normpath(directory))
if not os.path.isdir(resolved_dir):
    logger.error(f"Directory does not exist or is not a directory: {resolved_dir}")
    return

# Later, for each file:
abs_path = os.path.abspath(filepath)
if not abs_path.startswith(resolved_dir):
    logger.warning(f"Blocked path traversal attempt: {filepath}")
    continue
```

**No further action required.**

---

### 1.2 Pickle Deserialization Risk ❌ OUTSTANDING 🎯 DEMO-CRITICAL

**Original Issue**: `core/store.py:70-71` - BM25 index loaded from pickle without validation.

**Current Status**: OUTSTANDING - Still using unsafe pickle deserialization.

**Evidence**: `core/store.py` lines 84-85, 122-123, 138-139:
```python
# Line 84-85 (load during incremental build):
with open(self.save_path, "rb") as f:
    existing_bm25, existing_chunk_map = pickle.load(f)

# Line 122-123 (save):
with open(self.save_path, "wb") as f:
    pickle.dump((self.bm25, self.chunk_map), f)

# Line 138-139 (load):
with open(self.save_path, "rb") as f:
    self.bm25, self.chunk_map = pickle.load(f)
```

**Why Critical for Demo**: If someone clones the repo with a malicious `bm25_index.pkl`, they get RCE on first query.

**Remediation Options** (choose one):

1. **Option A: HMAC Signature Validation** (Recommended for demo)
   ```python
   import hmac
   import hashlib
   
   SECRET_KEY = os.environ.get("BM25_SECRET", "demo-secret-key")
   
   def save_index(self, data, path):
       serialized = pickle.dumps(data)
       signature = hmac.new(SECRET_KEY.encode(), serialized, hashlib.sha256).hexdigest()
       with open(path, "wb") as f:
           f.write(signature.encode() + b"\n" + serialized)
   
   def load_index(self, path):
       with open(path, "rb") as f:
           content = f.read()
       sig_end = content.index(b"\n")
       signature = content[:sig_end].decode()
       serialized = content[sig_end+1:]
       expected = hmac.new(SECRET_KEY.encode(), serialized, hashlib.sha256).hexdigest()
       if not hmac.compare_digest(signature, expected):
           raise ValueError("BM25 index signature validation failed")
       return pickle.loads(serialized)
   ```

2. **Option B: JSON Serialization** (Safer but more work)
   - Serialize chunk_map as JSON (straightforward)
   - BM25Okapi internal state requires custom serialization

3. **Option C: Regenerate on Load** (Simplest)
   - Store only chunk texts in JSON
   - Rebuild BM25 index on load (adds ~100ms startup)

**Recommended**: Option A for demo, Option C for simplicity if startup time acceptable.

---

### 1.3 Prompt Injection Vulnerability ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: `core/generation.py:27` - User query directly concatenated into prompt.

**Current Status**: OUTSTANDING

**Evidence**: `core/generation.py` line 27:
```python
user_prompt = f"Context:\n{context_text}\n\nQuestion: {query}"
```

**Why MVP-Deferred**: For a local demo, the user is attacking themselves. Still, basic sanitization is good practice.

**Remediation** (when ready):
```python
def sanitize_query(query: str) -> str:
    """Basic sanitization to prevent prompt manipulation."""
    # Remove potential injection markers
    dangerous_patterns = [
        "ignore previous instructions",
        "ignore above",
        "disregard",
        "system prompt",
        "you are now",
    ]
    query_lower = query.lower()
    for pattern in dangerous_patterns:
        if pattern in query_lower:
            return "[Query contained suspicious patterns]"
    # Limit length
    return query[:2000]
```

---

### 1.4 No Input Validation ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: User inputs not validated across multiple locations.

**Current Status**: OUTSTANDING

**Evidence**: No validation on:
- `query` command: question string (any length, any content)
- `ingest` command: data_dir path (only path traversal checked)
- `eval` command: dataset_path (no validation)
- `query` command: model name passed directly to Ollama

**Remediation** (add to `core/cli.py`):
```python
from pydantic import BaseModel, Field, validator

class QueryInput(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=50)
    mode: str = Field("hybrid")
    model: str = Field("mistral")
    
    @validator("mode")
    def validate_mode(cls, v):
        if v not in ["dense", "lexical", "hybrid"]:
            raise ValueError("mode must be dense, lexical, or hybrid")
        return v
    
    @validator("model")
    def validate_model(cls, v):
        allowed = ["mistral", "llama2", "codellama", "phi"]
        if v not in allowed:
            raise ValueError(f"model must be one of {allowed}")
        return v
```

---

### 1.5 Resource Exhaustion ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: No limits on file size, chunk count, or memory usage.

**Current Status**: OUTSTANDING

**Evidence**: `core/ingest.py` lines 52-54 read entire file without size check:
```python
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()  # No size limit
```

**Remediation** (add to `Loader.load()`):
```python
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_CHUNK_COUNT = 10000

# In load():
file_size = os.path.getsize(filepath)
if file_size > MAX_FILE_SIZE_BYTES:
    logger.warning(f"Skipping {filepath}: exceeds {MAX_FILE_SIZE_BYTES} bytes")
    continue

# In Chunker.chunk():
if len(all_chunks) > MAX_CHUNK_COUNT:
    logger.warning(f"Chunk limit reached ({MAX_CHUNK_COUNT})")
    break
```

---

## 2. ARCHITECTURAL INCONSISTENCIES

### 2.1 Unimplemented `reset` Flag ✅ FIXED

**Original Issue**: `core/cli.py:21` - `reset` parameter accepted but never used.

**Current Status**: FIXED

**Evidence**: `core/cli.py` lines 37-45:
```python
if reset:
    import shutil
    if os.path.exists("chroma_db"):
        shutil.rmtree("chroma_db")
        console.print("[yellow]Removed ChromaDB directory[/yellow]")
    if os.path.exists("bm25_index.pkl"):
        os.remove("bm25_index.pkl")
        console.print("[yellow]Removed BM25 index[/yellow]")
    console.print("[bold]Index reset complete[/bold]")
```

**No further action required.**

---

### 2.2 Inconsistent Error Handling ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: Some functions catch exceptions, others don't. Error messages vary.

**Current Status**: OUTSTANDING

**Evidence**: Mixed patterns:
- `generation.py:36-38`: Catches all exceptions, returns generic string
- `ingest.py:65-66`: Catches per-file errors, logs, continues
- `store.py:114-115`: Catches load errors, logs warning, rebuilds
- `cli.py:146-148`: Catches retriever init errors, prints, returns

**Remediation** (when ready):
```python
# core/exceptions.py
class RAGError(Exception):
    """Base exception for RAG system."""
    pass

class IngestionError(RAGError):
    """Errors during document ingestion."""
    pass

class RetrievalError(RAGError):
    """Errors during retrieval."""
    pass

class GenerationError(RAGError):
    """Errors during LLM generation."""
    pass
```

---

### 2.3 Distance vs Similarity Score Confusion ❌ OUTSTANDING 🎯 DEMO-CRITICAL

**Original Issue**: ChromaDB returns distances (lower is better), but code treats them as scores.

**Current Status**: OUTSTANDING

**Evidence**: `core/store.py` line 63:
```python
"score": results["distances"][0][i] if "distances" in results else 0.0,
```

**Impact**: In RRF fusion, items are sorted by score descending. If using distances, lower distances (better matches) get sorted to the bottom.

**Remediation**:
```python
# Option 1: Convert distance to similarity (for L2 distance)
distance = results["distances"][0][i] if "distances" in results else 0.0
similarity = 1.0 / (1.0 + distance)  # Higher is better

# Option 2: Negate for ranking purposes
score = -distance  # Negative distance, so sorting descending works

# In VectorStore.query():
hits.append({
    "id": chunk_id,
    "score": 1.0 / (1.0 + results["distances"][0][i]) if "distances" in results else 0.0,
    "text": results["documents"][0][i],
    "metadata": results["metadatas"][0][i]
})
```

---

### 2.4 Naive Tokenization ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: BM25 uses simple `split(" ")` which fails for punctuation, non-English text.

**Current Status**: OUTSTANDING

**Evidence**: `core/store.py` lines 94, 118, 148:
```python
tokenized_corpus = [c.text.split(" ") for c in all_chunks]  # Line 94, 118
tokenized_query = query_text.split(" ")  # Line 148
```

**Remediation**:
```python
import re

def tokenize(text: str) -> list[str]:
    """Simple but effective tokenization."""
    # Lowercase, split on non-alphanumeric, filter empty
    tokens = re.split(r'\W+', text.lower())
    return [t for t in tokens if t and len(t) > 1]

# Usage:
tokenized_corpus = [tokenize(c.text) for c in chunks]
tokenized_query = tokenize(query_text)
```

For better quality (MVP):
```python
# pip install nltk
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer

stemmer = PorterStemmer()
def tokenize(text: str) -> list[str]:
    tokens = word_tokenize(text.lower())
    return [stemmer.stem(t) for t in tokens if t.isalnum()]
```

---

## 3. PERFORMANCE BOTTLENECKS

### 3.1 Embedding Model Cold Start ✅ FIXED

**Original Issue**: `Embedder` instantiated on every `VectorStore` creation, loading model each time.

**Current Status**: FIXED

**Evidence**: `core/embedding.py` lines 8-19:
```python
class Embedder:
    # Class-level cache for model instances
    _model_cache: dict = {}
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        # Use cached model if available, otherwise load and cache
        if model_name not in Embedder._model_cache:
            Embedder._model_cache[model_name] = SentenceTransformer(model_name)
        
        self.model = Embedder._model_cache[model_name]
```

**No further action required.**

---

### 3.2 Synchronous Operations ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: All I/O operations are synchronous.

**Current Status**: OUTSTANDING - This is acceptable for CLI demo.

**Remediation** (MVP):
- Use `asyncio` for I/O-bound operations
- Consider `aiofiles` for file reading
- Wrap Ollama calls with `asyncio.to_thread()`

---

### 3.3 BM25 Index Rebuild 🔶 PARTIAL

**Original Issue**: Entire BM25 index rebuilt from scratch on every ingest.

**Current Status**: PARTIAL - Incremental logic exists but has issues.

**Evidence**: `core/store.py` lines 75-113 implement incremental updates:
```python
def build(self, chunks: List[Chunk], incremental: bool = True):
    if incremental and existing_index:
        # Merge: add new chunks to existing index
        existing_chunk_ids = {c.id for c in existing_chunk_map.values()}
        new_chunks = [c for c in chunks if c.id not in existing_chunk_ids]
        # ...
```

**Remaining Issues**:
1. Still rebuilds entire BM25 object when adding new chunks (line 95)
2. No deletion of removed documents
3. The `incremental` flag is tied to `reset` flag logic which is confusing

**Full Fix** (MVP):
- Track document hashes for change detection
- Implement true incremental BM25 updates (or accept rebuild cost)
- Separate "incremental" concept from "reset" concept

---

### 3.4 No Batching ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: All chunks embedded in single batch, causing memory issues.

**Current Status**: OUTSTANDING

**Evidence**: `core/store.py` line 38:
```python
embeddings = self.embedder.embed(texts)  # All at once
```

**Remediation**:
```python
BATCH_SIZE = 100

def embed_batched(self, texts: List[str]) -> List[List[float]]:
    all_embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        embeddings = self.embedder.embed(batch)
        all_embeddings.extend(embeddings)
    return all_embeddings
```

---

### 3.5 No Connection Pooling ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: New ChromaDB client created for each operation.

**Current Status**: OUTSTANDING - Acceptable for CLI demo.

**Evidence**: `core/store.py` line 20:
```python
self.client = chromadb.PersistentClient(path=persist_directory)
```

---

### 3.6 No Batching for Upsert ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Current Status**: OUTSTANDING - ChromaDB handles this internally, but explicit batching could help.

---

## 4. SCALING LIMITATIONS

### 4.1 In-Memory BM25 Index ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: Entire `chunk_map` dictionary stored in memory.

**Current Status**: OUTSTANDING - Acceptable for demo corpus sizes.

---

### 4.2 No Pagination ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: All results returned at once.

**Current Status**: OUTSTANDING - Demo uses small `top_k` values.

---

### 4.3 Single-Threaded Processing ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: All processing in main thread.

**Current Status**: OUTSTANDING - Acceptable for demo.

---

### 4.4 No Rate Limiting ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: No protection against request flooding.

**Current Status**: OUTSTANDING - CLI has natural rate limiting (human typing speed).

---

### 4.5 No Concurrent Access Protection ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: No locking for concurrent writes.

**Current Status**: OUTSTANDING - CLI is single-user, single-process.

---

## 5. FUNCTIONAL GAPS

### 5.1 Missing Timeout Handling ❌ OUTSTANDING 🎯 DEMO-CRITICAL

**Original Issue**: Ollama API calls have no timeout.

**Current Status**: OUTSTANDING

**Evidence**: `core/generation.py` lines 31-34:
```python
response = ollama.chat(model=self.model_name, messages=[
    {'role': 'system', 'content': system_prompt},
    {'role': 'user', 'content': user_prompt},
])  # No timeout specified
```

**Impact**: Demo hangs indefinitely if Ollama is slow or unresponsive.

**Remediation**:
```python
import httpx

# Option 1: Use ollama library with custom client (if supported)
# Option 2: Direct HTTP call with timeout
def generate(self, query: str, context: List[Dict[str, Any]]) -> str:
    # ... prompt construction ...
    try:
        # Set timeout (connection=5s, read=60s for generation)
        response = ollama.chat(
            model=self.model_name, 
            messages=[...],
            options={"timeout": 60}  # Check if ollama lib supports this
        )
        return response['message']['content']
    except Exception as e:
        if "timeout" in str(e).lower():
            return "Error: Request timed out. Is Ollama responsive?"
        raise
```

**Note**: The `ollama` Python library uses `httpx` internally. Check if it supports timeout configuration.

---

### 5.2 No Retry Logic ❌ OUTSTANDING 🎯 DEMO-CRITICAL

**Original Issue**: Transient failures cause immediate failure.

**Current Status**: OUTSTANDING

**Remediation**:
```python
import time

def generate_with_retry(self, query: str, context: List[Dict], max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            return self._generate_internal(query, context)
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(f"Generation failed (attempt {attempt+1}), retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"Generation failed after {max_retries} attempts: {e}")
                return f"Error: Failed after {max_retries} attempts. Last error: {e}"
```

---

### 5.3 No File Size Limits ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: Files read entirely into memory without size checks.

**Current Status**: OUTSTANDING

See remediation in section 1.5.

---

### 5.4 No Incremental Updates 🔶 PARTIAL

**Original Issue**: Every ingest rebuilds entire index.

**Current Status**: PARTIAL - See section 3.3.

---

### 5.5 Missing Observability ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: Telemetry only logs to files.

**Current Status**: OUTSTANDING - Acceptable for demo (logs exist in `logs/*.jsonl`).

---

## 6. DATA INTEGRITY ISSUES

### 6.1 No Transaction Support ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: VectorStore and LexicalIndex updates not atomic.

**Current Status**: OUTSTANDING - Acceptable for single-user demo.

---

### 6.2 No Data Validation ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: Pydantic models don't validate content.

**Current Status**: OUTSTANDING

**Evidence**: `core/models.py` has no validators:
```python
class Document(BaseModel):
    id: str
    content: str  # No min/max length
    source: str   # No validation
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

**Remediation**:
```python
from pydantic import BaseModel, Field, validator

class Document(BaseModel):
    id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    @validator("content")
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError("content cannot be empty or whitespace only")
        return v
```

---

### 6.3 Chunk ID Collision Risk ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: SHA1 hashing could theoretically collide.

**Current Status**: OUTSTANDING - Probability negligible for demo scale.

**Remediation** (when ready): Switch to SHA256
```python
import hashlib

def compute_id(doc_id: str, text: str, start: int, end: int) -> str:
    raw = f"{doc_id}:{start}:{end}:{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

---

## 7. CODE QUALITY ISSUES

### 7.1 Unused Imports ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: `Settings` imported but never used.

**Current Status**: OUTSTANDING

**Evidence**: `core/store.py` line 6:
```python
from chromadb.config import Settings  # Never used
```

**Remediation**: Remove the unused import:
```python
# Remove this line:
# from chromadb.config import Settings
```

---

### 7.2 Magic Numbers ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: RRF `k=60` is hardcoded.

**Current Status**: OUTSTANDING

**Evidence**: `core/retrieval.py` line 32:
```python
def _rrf_fusion(self, dense: List[Dict], lexical: List[Dict], k: int = 60, top_k: int = 5):
```

**Remediation**: Make configurable via environment or constant:
```python
import os

RRF_K = int(os.environ.get("RRF_K", "60"))

# In class:
def _rrf_fusion(self, dense, lexical, k: int = RRF_K, top_k: int = 5):
```

---

### 7.3 Incomplete Error Messages ❌ OUTSTANDING 📋 DEMO-RECOMMENDED

**Original Issue**: Generic error message doesn't help diagnose issues.

**Current Status**: OUTSTANDING

**Evidence**: `core/generation.py` line 38:
```python
return "Error calling Ollama. Is 'ollama serve' running?"
```

**Remediation**:
```python
except ollama.ResponseError as e:
    return f"Ollama error: {e.error} (status: {e.status_code})"
except ConnectionError:
    return "Error: Cannot connect to Ollama. Is 'ollama serve' running?"
except TimeoutError:
    return "Error: Ollama request timed out. Try a shorter query or check Ollama status."
except Exception as e:
    return f"Error calling Ollama: {type(e).__name__}: {e}"
```

---

## 8. TESTING GAPS

### 8.1 Limited Test Coverage ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: Only 3 basic tests, no integration/security tests.

**Current Status**: OUTSTANDING

**Evidence**: `tests/test_core.py` has only:
- `test_stable_id()`
- `test_chunking_determinism()`
- `test_loader_missing_dir()`

**Recommended Tests to Add**:
- Path traversal rejection test
- BM25 incremental update test
- RRF fusion correctness test
- End-to-end query test (mock Ollama)
- File size limit test

---

### 8.2 No Performance Tests ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: No benchmarks for ingestion/query performance.

**Current Status**: OUTSTANDING

---

## 9. DEPLOYMENT & OPERATIONS

### 9.1 No Configuration Management ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: Paths, model names, parameters hardcoded.

**Current Status**: OUTSTANDING

**Evidence**: Hardcoded values throughout:
- `"chroma_db"` in store.py
- `"bm25_index.pkl"` in store.py
- `"all-MiniLM-L6-v2"` in embedding.py
- `"mistral"` in generation.py/cli.py

**Remediation** (when ready):
```python
# core/config.py
import os

class Config:
    CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "chroma_db")
    BM25_INDEX_PATH = os.environ.get("BM25_INDEX_PATH", "bm25_index.pkl")
    EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    LLM_MODEL = os.environ.get("LLM_MODEL", "mistral")
    DATA_DIR = os.environ.get("DATA_DIR", "data/corpus")
```

---

### 9.2 No Health Checks ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: `check` command not comprehensive.

**Current Status**: PARTIAL - Basic check exists in `cli.py:197-231`.

---

### 9.3 Logging to File Only ❌ OUTSTANDING 🔮 MVP-DEFERRED

**Original Issue**: Logs only written to file.

**Current Status**: OUTSTANDING - Both file and console (Rich) handlers exist.

**Evidence**: `core/logging_config.py` lines 14-17:
```python
handlers=[
    RichHandler(rich_tracebacks=True),  # Console
    logging.FileHandler(file_name)       # File
]
```

This is actually better than stated in the review.

---

## 10. CLEANUP REQUIRED

### 10.1 Debug Logging Artifacts 📋 DEMO-RECOMMENDED

**Issue**: Debug logging code scattered throughout codebase.

**Locations**:
- `core/cli.py` lines 26-33 (`#region agent log`)
- `core/ingest.py` lines 15-23, 35-44, 137-145, 160-168
- `core/store.py` lines 15-31, 76-79, 103-112, 124-133

**Remediation**: Remove all `#region agent log` blocks that write to `.cursor/debug.log`.

Example to remove from `core/cli.py`:
```python
# DELETE THIS BLOCK:
# #region agent log
import json
try:
    with open(r"d:\Repos\rag-light-demo\.cursor\debug.log", "a", encoding="utf-8") as f:
        log_entry = {...}
        f.write(json.dumps(log_entry) + "\n")
except: pass
# #endregion
```

---

## 11. PRIORITIZED ACTION PLAN

### Phase 1: Demo-Critical (Do Now)

| Issue | File | Effort | Impact |
|-------|------|--------|--------|
| 1.2 Pickle Risk | store.py | 30 min | Prevents RCE |
| 2.3 Distance/Similarity | store.py | 5 min | Fixes ranking |
| 5.1 Timeout Handling | generation.py | 15 min | Prevents hangs |
| 5.2 Retry Logic | generation.py | 15 min | Improves reliability |

### Phase 2: Demo-Recommended (Polish)

| Issue | File | Effort | Impact |
|-------|------|--------|--------|
| 7.1 Unused Import | store.py | 1 min | Code cleanliness |
| 7.2 Magic Numbers | retrieval.py | 5 min | Configurability |
| 7.3 Error Messages | generation.py | 10 min | UX improvement |
| 2.4 Tokenization | store.py | 15 min | Better BM25 |
| 1.4 Input Validation | cli.py | 20 min | Robustness |
| 1.5 File Size Limits | ingest.py | 10 min | Prevents memory issues |
| 6.2 Data Validation | models.py | 15 min | Data quality |
| 10.1 Debug Cleanup | multiple | 20 min | Production readiness |

### Phase 3: MVP-Deferred

All issues marked 🔮 MVP-DEFERRED can wait until scaling for production.

---

## 12. VERIFICATION CHECKLIST

After implementing fixes, verify:

- [ ] `make ingest` works with reset flag: `python -m core.cli ingest --reset`
- [ ] `make query Q="test"` returns results with correct similarity scores (higher = better)
- [ ] Query with Ollama stopped returns timeout error within reasonable time
- [ ] Transient failure (restart Ollama mid-query) retries successfully
- [ ] Large file in corpus gets rejected with warning
- [ ] Path traversal attempt (`--data-dir ../..`) is blocked
- [ ] Debug log code removed (no writes to `.cursor/debug.log`)
- [ ] All tests pass: `python -m pytest tests/`

---

*Document generated based on SECURITY_ARCHITECTURE_REVIEW.md analysis*
*Last updated: 2024*

