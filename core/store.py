import os
import pickle
import hmac
import hashlib
import re
import chromadb
from typing import List, Dict, Any
from rank_bm25 import BM25Okapi
from core.models import Chunk
from core.embedding import Embedder
from core.logging_config import logger

# Secret key for HMAC signature validation (use environment variable in production)
BM25_SECRET_KEY = os.environ.get("BM25_SECRET_KEY", "rag-demo-secret-key-change-in-prod")


def tokenize(text: str) -> List[str]:
    """
    Improved tokenization for BM25.
    Lowercases, splits on non-alphanumeric, filters short tokens.
    """
    tokens = re.split(r'\W+', text.lower())
    return [t for t in tokens if t and len(t) > 1]


class VectorStore:
    def __init__(self, persist_directory: str = "chroma_db", collection_name: str = "rag_demo"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.embedder = Embedder()  # Uses cached model if available

    def upsert(self, chunks: List[Chunk]):
        if not chunks:
            return
        
        texts = [c.text for c in chunks]
        embeddings = self.embedder.embed(texts)
        ids = [c.id for c in chunks]
        metadatas = [{"doc_id": c.doc_id, **c.metadata} for c in chunks]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas
        )
        logger.info(f"Upserted {len(chunks)} vectors to ChromaDB.")

    def query(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.embedder.embed([query_text])[0]
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        
        # Flatten chroma results and convert distance to similarity
        hits = []
        if results["ids"]:
            for i, chunk_id in enumerate(results["ids"][0]):
                # ChromaDB returns L2 distance (lower = better)
                # Convert to similarity: 1 / (1 + distance) so higher = better
                distance = results["distances"][0][i] if "distances" in results else 0.0
                similarity = 1.0 / (1.0 + distance)
                
                hits.append({
                    "id": chunk_id,
                    "score": similarity,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i]
                })
        return hits


class LexicalIndex:
    def __init__(self, save_path: str = "bm25_index.pkl"):
        self.save_path = save_path
        self.bm25 = None
        self.chunk_map = {}  # Map index to chunk ID/Text for retrieval

    def _compute_signature(self, data: bytes) -> str:
        """Compute HMAC-SHA256 signature for data integrity."""
        return hmac.new(
            BM25_SECRET_KEY.encode(), 
            data, 
            hashlib.sha256
        ).hexdigest()

    def _save_with_signature(self, data: tuple):
        """Save pickle data with HMAC signature for integrity verification."""
        serialized = pickle.dumps(data)
        signature = self._compute_signature(serialized)
        
        with open(self.save_path, "wb") as f:
            # Write signature (64 hex chars) + newline + data
            f.write(signature.encode() + b"\n" + serialized)
        
        logger.info(f"Saved BM25 index with integrity signature to {self.save_path}")

    def _load_with_signature(self) -> tuple:
        """Load pickle data and verify HMAC signature."""
        with open(self.save_path, "rb") as f:
            content = f.read()
        
        # Find signature boundary
        sig_end = content.index(b"\n")
        signature = content[:sig_end].decode()
        serialized = content[sig_end + 1:]
        
        # Verify signature
        expected = self._compute_signature(serialized)
        if not hmac.compare_digest(signature, expected):
            raise ValueError(
                "BM25 index signature validation failed! "
                "The index file may be corrupted or tampered with. "
                "Run 'ingest --reset' to rebuild the index."
            )
        
        return pickle.loads(serialized)

    def build(self, chunks: List[Chunk], incremental: bool = True):
        existing_index = os.path.exists(self.save_path)
        
        # Incremental update: load existing index and merge if it exists
        if incremental and existing_index:
            try:
                existing_bm25, existing_chunk_map = self._load_with_signature()
                
                # Merge: add new chunks to existing index
                existing_chunk_ids = {c.id for c in existing_chunk_map.values()}
                new_chunks = [c for c in chunks if c.id not in existing_chunk_ids]
                
                if new_chunks:
                    # Rebuild with all chunks (existing + new)
                    all_chunks = list(existing_chunk_map.values()) + new_chunks
                    tokenized_corpus = [tokenize(c.text) for c in all_chunks]
                    self.bm25 = BM25Okapi(tokenized_corpus)
                    self.chunk_map = {i: c for i, c in enumerate(all_chunks)}
                    logger.info(f"Incremental update: added {len(new_chunks)} new chunks to existing {len(existing_chunk_map)} chunks")
                else:
                    # No new chunks, reuse existing index
                    self.bm25 = existing_bm25
                    self.chunk_map = existing_chunk_map
                    logger.info("No new chunks to add, reusing existing BM25 index")
                    return
            except ValueError as e:
                # Signature validation failed
                logger.error(str(e))
                raise
            except Exception as e:
                logger.warning(f"Failed to load existing index for incremental update: {e}. Rebuilding from scratch.")
        
        # Full rebuild (first time or incremental failed)
        tokenized_corpus = [tokenize(c.text) for c in chunks]
        self.bm25 = BM25Okapi(tokenized_corpus)
        self.chunk_map = {i: c for i, c in enumerate(chunks)}
        
        self._save_with_signature((self.bm25, self.chunk_map))
        logger.info(f"Built and saved BM25 index to {self.save_path}")

    def load(self):
        if os.path.exists(self.save_path):
            try:
                self.bm25, self.chunk_map = self._load_with_signature()
                logger.info("Loaded BM25 index with verified signature.")
            except ValueError as e:
                logger.error(str(e))
                raise
            except Exception as e:
                # Handle legacy unsigned pickle files - migrate them
                logger.warning(f"Failed to load signed index: {e}. Attempting legacy load and migration...")
                try:
                    with open(self.save_path, "rb") as f:
                        self.bm25, self.chunk_map = pickle.load(f)
                    # Re-save with signature
                    self._save_with_signature((self.bm25, self.chunk_map))
                    logger.info("Migrated legacy BM25 index to signed format.")
                except Exception as e2:
                    logger.error(f"Failed to load legacy index: {e2}. Please run 'ingest --reset'.")
                    raise
        else:
            logger.warning("No BM25 index found. Please run ingest.")

    def query(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.bm25:
            return []
        
        tokenized_query = tokenize(query_text)
        # get_top_n doesn't return scores easily in older versions, using get_scores
        scores = self.bm25.get_scores(tokenized_query)
        top_n_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        
        hits = []
        for i in top_n_indices:
            chunk = self.chunk_map[i]
            hits.append({
                "id": chunk.id,
                "score": scores[i],
                "text": chunk.text,
                "metadata": chunk.metadata
            })
        return hits
