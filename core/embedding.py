"""
Embedder with multi-level caching for query embeddings.

Caching strategy:
- L1: In-memory LRU cache (fastest, volatile)
- L2: Disk-backed cache via diskcache (persists across CLI runs)

Cache key normalization:
- Strip whitespace
- Collapse internal whitespace to single spaces
- Include model name in key
"""

import os
import hashlib
from functools import lru_cache
from typing import List, Optional, Tuple

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    import diskcache
except ImportError:
    diskcache = None

from core.logging_config import logger

# Configuration via environment
EMBEDDING_CACHE_ENABLED = os.environ.get("EMBEDDING_CACHE_ENABLED", "1").lower() in ("1", "true", "yes")
EMBEDDING_CACHE_DIR = os.environ.get("EMBEDDING_CACHE_DIR", ".cache/embeddings")
EMBEDDING_CACHE_SIZE_MB = int(os.environ.get("EMBEDDING_CACHE_SIZE_MB", "100"))
EMBEDDING_LRU_MAXSIZE = int(os.environ.get("EMBEDDING_LRU_MAXSIZE", "256"))


def _normalize_query(text: str) -> str:
    """
    Normalize query text for stable cache keys.
    
    - Strips leading/trailing whitespace
    - Collapses internal whitespace to single spaces
    - Does NOT lowercase (embedding models may be case-sensitive)
    """
    return " ".join(text.split())


def _cache_key(model_name: str, text: str) -> str:
    """Generate a cache key from model name and normalized text."""
    normalized = _normalize_query(text)
    # Use hash for potentially long queries
    text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"embed:{model_name}:{text_hash}"


class Embedder:
    """
    Text embedder with model caching and query embedding caching.
    
    Model Cache (class-level):
    - SentenceTransformer models are cached to avoid reload overhead.
    
    Embedding Cache (instance-level, shared via disk):
    - L1: In-memory LRU for hot queries
    - L2: Disk cache for persistence across CLI invocations
    """
    
    # Class-level cache for model instances
    _model_cache: dict = {}
    
    # Class-level disk cache (shared across instances)
    _disk_cache: Optional["diskcache.Cache"] = None
    _disk_cache_initialized: bool = False
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers is not installed.")
        
        # Use cached model if available, otherwise load and cache
        if model_name not in Embedder._model_cache:
            logger.info(f"Loading embedding model: {model_name}")
            Embedder._model_cache[model_name] = SentenceTransformer(model_name)
        
        self.model = Embedder._model_cache[model_name]
        self.model_name = model_name
        
        # Initialize disk cache (once per class)
        self._init_disk_cache()
    
    @classmethod
    def _init_disk_cache(cls) -> None:
        """Initialize the disk cache (class-level, thread-safe initialization)."""
        if cls._disk_cache_initialized:
            return
        
        cls._disk_cache_initialized = True
        
        if not EMBEDDING_CACHE_ENABLED:
            logger.info("Embedding cache disabled via EMBEDDING_CACHE_ENABLED=0")
            return
        
        if diskcache is None:
            logger.warning("diskcache not installed; using in-memory cache only")
            return
        
        try:
            os.makedirs(EMBEDDING_CACHE_DIR, exist_ok=True)
            cls._disk_cache = diskcache.Cache(
                EMBEDDING_CACHE_DIR,
                size_limit=EMBEDDING_CACHE_SIZE_MB * 1024 * 1024
            )
            logger.info(f"Initialized embedding disk cache at {EMBEDDING_CACHE_DIR}")
        except Exception as e:
            logger.warning(f"Failed to initialize disk cache: {e}. Using in-memory only.")
            cls._disk_cache = None

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of texts (batch mode, no caching).
        
        Used for document ingestion where texts are unique.
        """
        return self.model.encode(texts, convert_to_numpy=True).tolist()
    
    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single query with multi-level caching.
        
        Cache lookup order:
        1. L1: In-memory LRU cache
        2. L2: Disk cache
        3. Miss: Compute embedding, store in both caches
        
        Returns:
            Embedding vector as list of floats
        """
        if not EMBEDDING_CACHE_ENABLED:
            return self.embed([query])[0]
        
        # Generate cache key
        key = _cache_key(self.model_name, query)
        
        # L1: Check in-memory LRU cache
        cached = self._get_from_lru(key)
        if cached is not None:
            logger.debug(f"Embedding cache L1 hit for query")
            return list(cached)
        
        # L2: Check disk cache
        if self._disk_cache is not None:
            try:
                disk_result = self._disk_cache.get(key)
                if disk_result is not None:
                    logger.debug(f"Embedding cache L2 hit for query")
                    # Promote to L1
                    self._set_to_lru(key, tuple(disk_result))
                    return disk_result
            except Exception as e:
                logger.warning(f"Disk cache read error: {e}")
        
        # Cache miss: compute embedding
        logger.debug(f"Embedding cache miss - computing")
        embedding = self.embed([query])[0]
        
        # Store in L1 (LRU)
        self._set_to_lru(key, tuple(embedding))
        
        # Store in L2 (disk)
        if self._disk_cache is not None:
            try:
                self._disk_cache.set(key, embedding)
            except Exception as e:
                logger.warning(f"Disk cache write error: {e}")
        
        return embedding
    
    @staticmethod
    @lru_cache(maxsize=EMBEDDING_LRU_MAXSIZE)
    def _lru_store(key: str) -> Optional[Tuple[float, ...]]:
        """
        LRU cache storage. Returns None for cache miss.
        
        Note: We use a separate method to allow cache inspection/clearing.
        """
        return None  # Default is miss; actual storage is via _set_to_lru
    
    def _get_from_lru(self, key: str) -> Optional[Tuple[float, ...]]:
        """Get from LRU cache, returning None on miss."""
        # Check if key exists in the manual store
        return getattr(self, '_lru_manual', {}).get(key)
    
    def _set_to_lru(self, key: str, value: Tuple[float, ...]) -> None:
        """Store in LRU-like manual cache."""
        if not hasattr(self, '_lru_manual'):
            self._lru_manual = {}
        
        # Simple bounded dict (LRU-like)
        if len(self._lru_manual) >= EMBEDDING_LRU_MAXSIZE:
            # Remove oldest (first) item
            oldest_key = next(iter(self._lru_manual))
            del self._lru_manual[oldest_key]
        
        self._lru_manual[key] = value
    
    @classmethod
    def clear_cache(cls):
        """Clear all caches (useful for testing or memory management)."""
        cls._model_cache.clear()
        
        if cls._disk_cache is not None:
            try:
                cls._disk_cache.clear()
                logger.info("Cleared embedding disk cache")
            except Exception as e:
                logger.warning(f"Failed to clear disk cache: {e}")
    
    @classmethod
    def get_cache_stats(cls) -> dict:
        """Get cache statistics for monitoring."""
        stats = {
            "models_loaded": list(cls._model_cache.keys()),
            "disk_cache_enabled": cls._disk_cache is not None,
        }
        
        if cls._disk_cache is not None:
            try:
                stats["disk_cache_size"] = len(cls._disk_cache)
                stats["disk_cache_volume"] = cls._disk_cache.volume()
            except Exception:
                pass
        
        return stats
