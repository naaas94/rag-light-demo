# Architecture Assessment & Delivery Plan

## 1. System Overview
The `rag-light-demo` successfully implements a "Local Production" architecture. It correctly identifies the key missing pieces in standard tutorials (Stability, IDs, Observability) and implements them in a lightweight, local-first manner.

**Status**: 🟢 **Functional Protocol**
The core `ingest -> store -> retrieve` loop is logically sound. Tests pass.

## 2. Tension & Critique (The "Red Team" View)
To ensure this demo survives a client presentation, we must address the following fragility points:

### A. The "Cold Start" Latency
**Problem**: The CLI initializes the Embedding Model (`all-MiniLM-L6-v2`) on *every command*.
**Risk**: running `python -m core.cli query "..."` will hang for 2-5 seconds just loading torch/transformers before doing any work. This feels "slow" to a client expecting instantaneous CLI feedback.
**Mitigation**: Use a lazy loader or a lightweight caching mechanism for the model, though difficult in a stateless CLI. (Acceptable for demo if warned).

### B. The Mocked Evaluation
**Problem**: `core.cli eval` returns hardcoded numbers.
**Risk**: If a client asks "How does it handle X?", and we run `eval` and get the exact same numbers, credibility is lost.
**Mitigation**: Implement a *real* (but small) logical evaluation loop using exact string matching or a regex heuristic if we don't want to use an LLM-as-judge for speed.

### C. Dependency on Ollama
**Problem**: The system implies `ollama serve` is running.
**Risk**: "Connection Refused" stack trace during demo.
**Mitigation**: Add a `check` command or a friendly error message that detects connection failure and tells the user exactly what to do.

### D. Simple Chunker Edge Cases
**Problem**: The current `Chunker` uses a simplified sliding window.
**Risk**: It relies on `text.rfind` with an estimated window. It might slice words in half or create invalid overlapping logic in complex edge cases.
**Mitigation**: Replace with a slightly more robust implementation or add unit tests for edge cases.

## 3. Concrete Steps to "Demo Ready"

I propose we execute the following 3-step plan immediately:

### Step 1: Robust & Real Evaluation
**Action**: Replace the mocked `eval` command with a functional one.
**Detail**: 
- Create a `data/eval/questions.jsonl` with 5-10 QA pairs.
- Implement `HitRate@K` (Is the correct Document ID in the top K?). This is deterministic and fast.
- *Why*: This proves "Retrieval Accuracy" without needing an LLM.

### Step 2: "Sanity Check" Command
**Action**: Add `python -m core.cli check`
**Detail**: 
- Verifies `data/corpus` exists.
- Verifies `ollama` is reachable.
- Verifies `chroma_db` is populated.
- *Why*: Run this 10 mins before the meeting to sleep at night.

### Step 3: Fix Chunker Logic
**Action**: Refactor `core/ingest.py`.
**Detail**: The current logic has a `pass` statement and some complexity around `rfind` that looks suspicious. We should simplify it to a standard overlapping window to ensure no data loss.

## 4. Next Actions
Shall I proceed with **Step 1 (Real Evaluation)**? This provides the highest ROI for a "system engineer" pitch.
