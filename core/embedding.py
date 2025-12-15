from typing import List, Optional
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

class Embedder:
    # Class-level cache for model instances
    _model_cache: dict = {}
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        if SentenceTransformer is None:
            raise ImportError("sentence-transformers is not installed.")
        
        # Use cached model if available, otherwise load and cache
        if model_name not in Embedder._model_cache:
            Embedder._model_cache[model_name] = SentenceTransformer(model_name)
        
        self.model = Embedder._model_cache[model_name]
        self.model_name = model_name

    def embed(self, texts: List[str]) -> List[List[float]]:
        # Casting to list[float] because numpy array is returned
        return self.model.encode(texts, convert_to_numpy=True).tolist()
    
    @classmethod
    def clear_cache(cls):
        """Clear the model cache (useful for testing or memory management)."""
        cls._model_cache.clear()
