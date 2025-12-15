from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
import hashlib


class Document(BaseModel):
    """Represents a source document loaded from disk."""
    id: str = Field(..., min_length=1, description="Unique document identifier (hash-based)")
    content: str = Field(..., min_length=1, description="Document text content")
    source: str = Field(..., min_length=1, description="Source file path")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        """Validate that content is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("content cannot be empty or whitespace only")
        return v

    @field_validator("source")
    @classmethod
    def source_not_empty(cls, v: str) -> str:
        """Validate that source path is not empty."""
        if not v or not v.strip():
            raise ValueError("source cannot be empty or whitespace only")
        return v

    @staticmethod
    def compute_id(source: str, content: str) -> str:
        """Computes a stable SHA256 hash for the document based on source and content."""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return hashlib.sha256(f"{source}:{content_hash}".encode("utf-8")).hexdigest()


class Chunk(BaseModel):
    """Represents a text chunk derived from a document."""
    id: str = Field(..., min_length=1, description="Unique chunk identifier (hash-based)")
    doc_id: str = Field(..., min_length=1, description="Parent document ID")
    text: str = Field(..., min_length=1, description="Chunk text content")
    start_char: int = Field(..., ge=0, description="Start character position in source document")
    end_char: int = Field(..., ge=0, description="End character position in source document")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Inherited metadata from document")
    embedding: Optional[List[float]] = Field(None, description="Optional embedding vector")

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        """Validate that text is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("text cannot be empty or whitespace only")
        return v

    @staticmethod
    def compute_id(doc_id: str, text: str, start: int, end: int) -> str:
        """Computes a stable SHA256 hash for the chunk."""
        raw = f"{doc_id}:{start}:{end}:{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Input validation models for CLI commands
class QueryInput(BaseModel):
    """Validates query command inputs."""
    question: str = Field(..., min_length=1, max_length=10000, description="User question")
    top_k: int = Field(5, ge=1, le=100, description="Number of chunks to retrieve")
    mode: str = Field("hybrid", description="Retrieval mode")
    model: str = Field("mistral", description="Ollama model name")

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        """Validate question is not empty."""
        if not v or not v.strip():
            raise ValueError("question cannot be empty")
        return v.strip()

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validate retrieval mode."""
        valid_modes = ["dense", "lexical", "hybrid"]
        if v not in valid_modes:
            raise ValueError(f"mode must be one of {valid_modes}")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        """Validate model name (basic sanity check)."""
        if not v or not v.strip():
            raise ValueError("model name cannot be empty")
        # Allow any alphanumeric model name with common separators
        import re
        if not re.match(r'^[a-zA-Z0-9_\-.:]+$', v):
            raise ValueError("model name contains invalid characters")
        return v


class IngestInput(BaseModel):
    """Validates ingest command inputs."""
    data_dir: str = Field(..., min_length=1, description="Directory to ingest from")
    reset: bool = Field(False, description="Whether to reset indices")

    @field_validator("data_dir")
    @classmethod
    def validate_data_dir(cls, v: str) -> str:
        """Validate data directory path."""
        if not v or not v.strip():
            raise ValueError("data_dir cannot be empty")
        # Basic path injection prevention
        if "\x00" in v:
            raise ValueError("data_dir contains null bytes")
        return v
