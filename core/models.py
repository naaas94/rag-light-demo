from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import hashlib

class Document(BaseModel):
    id: str
    content: str
    source: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def compute_id(source: str, content: str) -> str:
        """Computes a stable hash for the document based on source and content."""
        content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()
        return hashlib.sha1(f"{source}:{content_hash}".encode("utf-8")).hexdigest()

class Chunk(BaseModel):
    id: str
    doc_id: str
    text: str
    start_char: int
    end_char: int
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None

    @staticmethod
    def compute_id(doc_id: str, text: str, start: int, end: int) -> str:
        """Computes a stable hash for the chunk."""
        raw = f"{doc_id}:{start}:{end}:{text}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
