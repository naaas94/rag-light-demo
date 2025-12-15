"""
RAGService: Long-lived singleton that owns all expensive resources.

This module addresses the optimization recommendation to avoid re-initializing
VectorStore, LexicalIndex, Retriever, and Generator per query.
"""

import os
from typing import Optional
from core.store import VectorStore, LexicalIndex
from core.retrieval import Retriever
from core.generation import Generator
from core.logging_config import logger


class RAGService:
    """
    Singleton service that holds all RAG components in memory for reuse.
    
    Benefits:
    - VectorStore/Chroma client initialized once
    - LexicalIndex/BM25 loaded once at startup
    - Generator with persistent Ollama client
    - Significantly reduced query latency (no repeated BM25 load + pickle verify)
    """
    
    _instance: Optional["RAGService"] = None
    
    def __init__(self):
        """Initialize all RAG components. Should only be called via get_instance()."""
        logger.info("Initializing RAGService (one-time setup)...")
        
        # Initialize vector store (Chroma persistent client)
        self.vector_store = VectorStore()
        
        # Initialize lexical index and pre-load BM25
        self.lexical_index = LexicalIndex()
        if os.path.exists(self.lexical_index.save_path):
            self.lexical_index.load()
            logger.info(f"Pre-loaded BM25 index with {len(self.lexical_index.chunk_map)} chunks")
        
        # Initialize retriever with shared stores
        self.retriever = Retriever(self.vector_store, self.lexical_index)
        
        # Generator will be lazily created per model (different queries may use different models)
        self._generators: dict = {}
        
        logger.info("RAGService initialized successfully")
    
    @classmethod
    def get_instance(cls) -> "RAGService":
        """
        Get or create the singleton RAGService instance.
        
        Thread-safety note: For CLI usage this is fine. For multi-threaded server,
        consider adding a lock or initializing at application startup.
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (useful for testing or after ingest)."""
        if cls._instance is not None:
            logger.info("Resetting RAGService instance")
            cls._instance = None
    
    def get_generator(self, model_name: str = "mistral") -> Generator:
        """
        Get a Generator for the specified model, creating if needed.
        
        Generators are cached per model name to reuse the Ollama client.
        """
        if model_name not in self._generators:
            self._generators[model_name] = Generator(model_name=model_name)
        return self._generators[model_name]
    
    def reload_indices(self) -> None:
        """
        Reload indices after an ingest operation.
        
        Call this after running ingest to pick up new chunks without
        restarting the process.
        """
        logger.info("Reloading indices...")
        
        # Reload BM25
        if os.path.exists(self.lexical_index.save_path):
            self.lexical_index.load()
            logger.info(f"Reloaded BM25 index with {len(self.lexical_index.chunk_map)} chunks")
        
        # VectorStore/Chroma automatically sees new data (persistent client)
        # but we can refresh the collection reference if needed
        self.vector_store = VectorStore()
        
        # Update retriever with refreshed stores
        self.retriever = Retriever(self.vector_store, self.lexical_index)
        
        logger.info("Indices reloaded successfully")

