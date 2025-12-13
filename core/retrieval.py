from typing import List, Dict, Any
from core.store import VectorStore, LexicalIndex
from core.logging_config import logger
from core.observability import trace

class Retriever:
    def __init__(self, vector_store: VectorStore, lexical_index: LexicalIndex):
        self.vector_store = vector_store
        self.lexical_index = lexical_index

    @trace("retrieve")
    def retrieve(self, query: str, top_k: int = 5, mode: str = "hybrid") -> List[Dict[str, Any]]:
        dense_results = []
        lexical_results = []

        if mode in ["dense", "hybrid"]:
            dense_results = self.vector_store.query(query, top_k=top_k)
        
        if mode in ["lexical", "hybrid"]:
            # Need to ensure index is loaded
            if not self.lexical_index.bm25:
                self.lexical_index.load()
            lexical_results = self.lexical_index.query(query, top_k=top_k)

        if mode == "dense":
            return dense_results
        if mode == "lexical":
            return lexical_results
        
        return self._rrf_fusion(dense_results, lexical_results, top_k=top_k)

    def _rrf_fusion(self, dense: List[Dict], lexical: List[Dict], k: int = 60, top_k: int = 5) -> List[Dict]:
        """
        Reciprocal Rank Fusion.
        score = 1 / (rank + k)
        """
        fused_scores = {}
        
        # Map IDs to content for reconstruction
        content_map = {}

        def process_list(results):
            for rank, item in enumerate(results):
                doc_id = item["id"]
                content_map[doc_id] = item
                if doc_id not in fused_scores:
                    fused_scores[doc_id] = 0.0
                fused_scores[doc_id] += 1 / (rank + k)

        process_list(dense)
        process_list(lexical)

        # Sort by fused score
        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)
        
        final_results = []
        for doc_id in sorted_ids[:top_k]:
            item = content_map[doc_id]
            item["score"] = fused_scores[doc_id] # Update score to fused score
            item["source"] = "fused"
            final_results.append(item)
            
        return final_results
