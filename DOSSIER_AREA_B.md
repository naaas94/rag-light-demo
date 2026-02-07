# Area B — Telemetry / Observability Habits

## Repo Scan Summary

| # | Artifact | Signal | Why |
|---|----------|--------|-----|
| 1 | `core/observability.py` | **Critical** | Custom trace/span engine; JSONL emitter; `@trace` decorator |
| 2 | `core/logging_config.py` | **Critical** | Structured logging (Rich + file handler), single logger `rag_core` |
| 3 | `core/cli.py` | **High** | Timing instrumentation (`retrieve_time`, `generate_time`, `total_time`), `cache-stats` command, `check` health probe, `eval` HitRate@K |
| 4 | `core/generation.py` | **High** | Context budget monitoring, retry/backoff with classified errors, timeout tracking |
| 5 | `core/embedding.py` | **High** | L1/L2 cache hit/miss logging, `get_cache_stats()`, disk cache volume monitoring |
| 6 | `core/service.py` | Medium | Singleton lifecycle logging, resource-reuse tracking |
| 7 | `core/store.py` | Medium | Upsert count logging, HMAC verification logging, BM25 signature failure paths |
| 8 | `core/ingest.py` | Medium | Resource-limit guardrails with logging (file size, chunk count) |
| 9 | `core/models.py` | Medium | Pydantic validators — data quality boundary that prevents bad telemetry |
| 10 | `ARCHITECTURE.md` | Medium | Documents the trace/span data model; mentions Datadog/Splunk JSONL compatibility |
| 11 | `README.md` | Low | Config table for all env vars; observability section |
| 12 | `.github/workflows/ci.yml` | Low | CI gate (tests only); no prod monitoring pipeline yet |

**Best dossier fit:** This repo is strongest for **Area B (Telemetry/Observability)** because it implements a hand-rolled but principled trace/span system, structured JSONL logging, multi-level cache metrics, context budget monitoring, error classification with retry telemetry, a health-check CLI, and an offline evaluation harness — all patterns that map directly to Autoptic's detect/diagnose/repair loop and cost-control philosophy.

---

## Observability Contract: RAG Request Trace Pipeline

### Location (evidence)

| Component | File | Symbol(s) | Search Token |
|-----------|------|-----------|--------------|
| Trace/Span engine | `core/observability.py` | `Telemetry`, `Telemetry.log_span`, `Telemetry.flush`, `trace` (decorator) | `"trace_id"` |
| Structured logger | `core/logging_config.py` | `setup_logger`, module-level `logger` | `"rag_core"` |
| Timing + health | `core/cli.py` | `query` (lines 108–175), `check` (lines 266–338), `cache_stats` (lines 347–385), `eval` (lines 178–262) | `"retrieve_time"`, `"generate_time"`, `"Total time"` |
| Retry telemetry | `core/generation.py` | `Generator.generate` (lines 122–180), `Generator._build_context` (lines 49–94) | `"Context budget reached"` |
| Cache metrics | `core/embedding.py` | `Embedder.embed_query` (lines 126–176), `Embedder.get_cache_stats` (lines 218–233) | `"Embedding cache L1 hit"`, `"Embedding cache L2 hit"`, `"Embedding cache miss"` |

### What gets emitted

**Traces (JSONL, one file per request):** `logs/trace_{trace_id}.jsonl`

Each span contains:

| Field | Type | Example |
|-------|------|---------|
| `trace_id` | UUID string | `"a1b2c3d4-..."` |
| `span_id` | UUID string | per-operation unique |
| `name` | string | `"retrieve"`, `"generate"` |
| `timestamp` | ISO 8601 | `"2026-02-07T14:30:01.123"` |
| `duration_ms` | float | `1423.7` |
| `input` | truncated string (500 chars) | query kwargs |
| `output` | truncated string (500 chars) | result or `{"error": "..."}` |

**Structured logs** (`rag_system.log` + Rich console):

- Initialization events (model load, service start, cache init)
- Cache L1/L2 hit/miss at DEBUG level
- Context budget breach at INFO level (included/dropped chunk counts)
- Error classification at ERROR level (type + attempt number)
- Retry backoff at INFO level

### What gets measured

| Metric | Where | Granularity |
|--------|-------|-------------|
| `retrieve_time` | `core/cli.py:124-126` | Per-query, wall-clock seconds |
| `generate_time` | `core/cli.py:165-167` | Per-query, wall-clock seconds |
| `total_time` | `core/cli.py:171` | Per-query, end-to-end |
| `duration_ms` per span | `core/observability.py:55` | Per-operation (retrieve, generate) |
| `HitRate@K` | `core/cli.py:257` | Per-eval-run, % of questions hitting ground-truth phrases |
| Cache entries count | `Embedder.get_cache_stats` | On-demand via `cache-stats` CLI |
| Cache volume (bytes) | `Embedder.get_cache_stats` | On-demand |
| Context budget utilization | `Generator._build_context:80-87` | Per-query: included vs dropped chunk counts |
| Retry attempt count | `Generator.generate:129-170` | Per-query: up to `OLLAMA_MAX_RETRIES` (default 3) |

### What triggers action

| Trigger | Mechanism | Location |
|---------|-----------|----------|
| Context budget exceeded | Automatic chunk dropping + INFO log | `core/generation.py:80-87` — `"Context budget reached ({MAX_CONTEXT_CHARS} chars)"` |
| Ollama timeout | Exponential backoff retry (1s, 2s, 4s) | `core/generation.py:166-170` — `wait_time = 2 ** attempt` |
| Connection failure | Retry + actionable error message (`"Is 'ollama serve' running?"`) | `core/generation.py:175-176` |
| Non-retryable error (404, 400) | Immediate bail with model-not-found message | `core/generation.py:138-139` — `e.status_code in (400, 404)` |
| BM25 signature mismatch | Hard stop + `"Run 'ingest --reset'"` runbook-style message | `core/store.py:121-126` — `hmac.compare_digest(signature, expected)` |
| File size limit exceeded | Skip file + WARNING log | `core/ingest.py:38-42` — `MAX_FILE_SIZE_BYTES` |
| Chunk count limit exceeded | Stop chunking + WARNING log | `core/ingest.py:147-151` — `MAX_CHUNK_COUNT` |
| System health degraded | `check` command probes 5 subsystems with pass/fail | `core/cli.py:266-338` |

### MTTR loop (concrete)

1. **Symptom** — User observes slow or failed query. The CLI prints per-phase timing (`retrieve_time`, `generate_time`) directly in the terminal output (`cli.py:172`). If generation fails, a classified error message is returned (timeout / connection / model-not-found).

2. **Instrumentation** — The `@trace("retrieve")` and `@trace("generate")` decorators (`observability.py:49-63`) automatically capture `duration_ms` and error payloads into JSONL spans. The trace file path is printed to the user: `"Trace saved to logs/trace_{trace_id}.jsonl"` (`cli.py:175`).

3. **Hypothesis** — Error classification in `generation.py:133-164` separates `ResponseError` (with status codes), `ConnectionError`, `TimeoutError`, and generic exceptions. This lets an operator immediately distinguish "model not loaded" from "Ollama down" from "prompt too large."

4. **Fix** — Transient failures auto-heal via exponential backoff (`generation.py:167-170`). Budget breaches auto-mitigate by dropping low-priority chunks (`generation.py:80-88`). Signature failures surface an explicit remediation step (`store.py:123-126`: `"Run 'ingest --reset'"`).

5. **Verify** — `python -m core.cli check` validates all 5 subsystems (data dir, ChromaDB, BM25 + signature, Ollama connectivity, cache state) in a single pass (`cli.py:266-338`). `cache-stats` confirms cache health post-fix (`cli.py:347-385`). Re-running `eval` provides a quantitative HitRate@K regression check (`cli.py:257`).

### (INFERENCE) Autoptic translation

- **Detect**: The JSONL trace pipeline (`observability.py`) emits structured spans with `duration_ms` and error payloads — this is the raw signal feed that Autoptic's change-resilience agents would ingest. The `check` command is a lightweight synthetic health probe, analogous to Autoptic's deterministic entity monitors.
- **Diagnose**: Error classification in `generation.py` (timeout vs. connection vs. model-not-found vs. generic) is a manual implementation of what PQL would express as deterministic diagnostic rules with guardrails. The per-phase timing breakdown (`retrieve_time` / `generate_time`) isolates bottlenecks, mapping to Autoptic's "symptom → root cause" reasoning.
- **Repair**: Auto-retry with exponential backoff and context-budget auto-truncation are self-healing patterns. In an Autoptic deployment, these would be codified as repair actions triggered by PQL-detected anomalies (e.g., `WHEN latency_p95 > 10s AND phase = "generate" THEN reduce_context_budget`).
- **Cost control**: The context budget (`MAX_CONTEXT_CHARS` = 8000) directly controls cost/request by capping token consumption. The multi-level embedding cache (L1 LRU + L2 disk with `EMBEDDING_CACHE_SIZE_MB` = 100) reduces compute cost for repeated queries. The `cache-stats` command enables observability-cost-containment audits.

### Key code snippets

**Snippet 1 — Trace/Span engine + decorator** (`core/observability.py`)

```python
class Telemetry:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        self.current_trace_id = None
        self.spans = []

    def start_trace(self) -> str:
        self.current_trace_id = str(uuid.uuid4())
        self.spans = []
        return self.current_trace_id

    def log_span(self, name, input_data=None, output_data=None, duration_ms=0.0):
        span = {
            "trace_id": self.current_trace_id,
            "span_id": str(uuid.uuid4()),
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "duration_ms": duration_ms,
            "input": str(input_data)[:500] if input_data else None,
            "output": str(output_data)[:500] if output_data else None
        }
        self.spans.append(span)
```

**Snippet 2 — Error-classified retry with exponential backoff** (`core/generation.py`)

```python
for attempt in range(self.max_retries):
    try:
        return self._generate_internal(query, context)
    except ollama.ResponseError as e:
        logger.error(f"Ollama response error (attempt {attempt+1}/{self.max_retries}): {e}")
        if hasattr(e, 'status_code') and e.status_code in (400, 404):
            return f"Error: Model '{self.model_name}' not found. {last_error}"
    except ConnectionError as e:
        logger.error(f"Connection error (attempt {attempt+1}/{self.max_retries}): {e}")
    except TimeoutError as e:
        logger.error(f"Timeout error (attempt {attempt+1}/{self.max_retries}): {e}")
    # Exponential backoff before retry (1s, 2s, 4s)
    if attempt < self.max_retries - 1:
        wait_time = 2 ** attempt
        logger.info(f"Retrying in {wait_time}s...")
        time.sleep(wait_time)
```

**Snippet 3 — Context budget control with drop-count telemetry** (`core/generation.py`)

```python
# Check budget
if total_chars + len(formatted) > MAX_CONTEXT_CHARS:
    remaining = len(context) - included_count
    if remaining > 0:
        logger.info(
            f"Context budget reached ({MAX_CONTEXT_CHARS} chars). "
            f"Included {included_count}/{len(context)} chunks, dropped {remaining}."
        )
    break

context_parts.append(formatted)
total_chars += len(formatted) + 2  # +2 for separator
included_count += 1
```

---

## Evidence Ledger Rows

| # | Claim | Evidence Type | File:Symbol | Search Token |
|---|-------|---------------|-------------|--------------|
| 1 | Hand-rolled trace/span engine emits JSONL with `trace_id`, `span_id`, `duration_ms`, `input`, `output` | EVIDENCE | `core/observability.py:Telemetry.log_span` | `"trace_id"` |
| 2 | `@trace` decorator auto-instruments `retrieve()` and `generate()` with timing + error capture | EVIDENCE | `core/observability.py:trace`, `core/retrieval.py:16`, `core/generation.py:122` | `@trace("retrieve")` |
| 3 | Traces flushed to `logs/trace_{trace_id}.jsonl`, one file per request | EVIDENCE | `core/observability.py:Telemetry.flush` | `trace_{self.current_trace_id}.jsonl` |
| 4 | ARCHITECTURE.md confirms JSONL format chosen for Datadog/Splunk ingestion compatibility | EVIDENCE | `ARCHITECTURE.md:26-30` | `"jsonl"` |
| 5 | Structured logger `rag_core` with Rich console + file handler (`rag_system.log`) | EVIDENCE | `core/logging_config.py:setup_logger` | `"rag_core"` |
| 6 | Per-query wall-clock timing: `retrieve_time`, `generate_time`, `total_time` displayed in CLI | EVIDENCE | `core/cli.py:124-126,165-167,171-172` | `"retrieve_time"` |
| 7 | Context budget guardrail at `MAX_CONTEXT_CHARS=8000`, logs included/dropped chunk counts | EVIDENCE | `core/generation.py:Generator._build_context:80-87` | `"Context budget reached"` |
| 8 | Error classification: `ResponseError`, `ConnectionError`, `TimeoutError`, generic — each logged with attempt counter | EVIDENCE | `core/generation.py:Generator.generate:133-164` | `"attempt {attempt + 1}"` |
| 9 | Exponential backoff retry: `wait_time = 2 ** attempt` (1s, 2s, 4s) | EVIDENCE | `core/generation.py:168` | `2 ** attempt` |
| 10 | L1/L2 cache hit/miss logging at DEBUG level | EVIDENCE | `core/embedding.py:Embedder.embed_query:147,155,163` | `"Embedding cache L1 hit"` |
| 11 | `get_cache_stats()` returns models_loaded, disk_cache_enabled, disk_cache_size, disk_cache_volume | EVIDENCE | `core/embedding.py:Embedder.get_cache_stats:219-233` | `"disk_cache_volume"` |
| 12 | `cache-stats` CLI command renders Rich table of cache health | EVIDENCE | `core/cli.py:cache_stats:347-385` | `"Cache Statistics"` |
| 13 | `check` CLI command probes 5 subsystems: data dir, ChromaDB count, BM25 + HMAC verify, Ollama connectivity, cache config | EVIDENCE | `core/cli.py:check:266-338` | `"Running System Sanity Check"` |
| 14 | `eval` CLI computes HitRate@K with per-query timing and total eval throughput | EVIDENCE | `core/cli.py:eval:257-261` | `"Overall Hit Rate@"` |
| 15 | Resource-limit guardrails (`MAX_FILE_SIZE_BYTES`, `MAX_CHUNK_COUNT`) log warnings on breach | EVIDENCE | `core/ingest.py:38-42,147-151` | `"exceeds limit"` |
| 16 | Non-retryable errors (HTTP 400/404) bail immediately instead of wasting retry budget | EVIDENCE | `core/generation.py:138-139` | `e.status_code in (400, 404)` |
| 17 | HMAC signature failure on BM25 index surfaces runbook-style remediation message | EVIDENCE | `core/store.py:LexicalIndex._load_with_signature:121-126` | `"Run 'ingest --reset'"` |
| 18 | Trace pipeline's JSONL format maps to Autoptic's telemetry ingestion for change-resilience detection | INFERENCE | — | — |
| 19 | Error classification + retry is a manual form of PQL detect/diagnose/repair rules with guardrails | INFERENCE | — | — |
| 20 | Context budget (`MAX_CONTEXT_CHARS`) is a cost-per-request control that maps to Autoptic's observability cost containment | INFERENCE | — | — |
