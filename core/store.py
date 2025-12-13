import os
import pickle
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any
from rank_bm25 import BM25Okapi
from core.models import Chunk
from core.embedding import Embedder
from core.logging_config import logger

class VectorStore:
    def __init__(self, persist_directory: str = "chroma_db", collection_name: str = "rag_demo"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.embedder = Embedder() # Instantiates the model

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
        
        # Flatten chroma results
        hits = []
        if results["ids"]:
            for i, chunk_id in enumerate(results["ids"][0]):
                hits.append({
                    "id": chunk_id,
                    "score": results["distances"][0][i] if "distances" in results else 0.0,
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i]
                })
        return hits

class LexicalIndex:
    def __init__(self, save_path: str = "bm25_index.pkl"):
        self.save_path = save_path
        self.bm25 = None
        self.chunk_map = {} # Map index to chunk ID/Text for retrieval

    def build(self, chunks: List[Chunk]):
        tokenized_corpus = [c.text.split(" ") for c in chunks] # Naive tokenization matching ingest
        self.bm25 = BM25Okapi(tokenized_corpus)
        self.chunk_map = {i: c for i, c in enumerate(chunks)}
        
        with open(self.save_path, "wb") as f:
            pickle.dump((self.bm25, self.chunk_map), f)
        logger.info(f"Built and saved BM25 index to {self.save_path}")

    def load(self):
        if os.path.exists(self.save_path):
            with open(self.save_path, "rb") as f:
                self.bm25, self.chunk_map = pickle.load(f)
            logger.info("Loaded BM25 index.")
        else:
            logger.warning("No BM25 index found. Please run ingest.")

    def query(self, query_text: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if not self.bm25:
            return []
        
        tokenized_query = query_text.split(" ")
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
