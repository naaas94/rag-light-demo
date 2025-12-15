"""
Generator with context budget controls and persistent Ollama client.

Optimizations:
- Ollama client created once in __init__ and reused
- Context budget controls to prevent prompt bloat
- Per-chunk truncation to cap context size
"""

import os
import time
import ollama
from typing import List, Dict, Any
from core.logging_config import logger
from core.observability import trace

# Configuration via environment variables
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))  # seconds
OLLAMA_MAX_RETRIES = int(os.environ.get("OLLAMA_MAX_RETRIES", "3"))

# Context budget controls (new)
MAX_CONTEXT_CHARS = int(os.environ.get("MAX_CONTEXT_CHARS", "8000"))  # Total context budget
MAX_CHUNK_CHARS = int(os.environ.get("MAX_CHUNK_CHARS", "1500"))  # Per-chunk limit


class Generator:
    def __init__(self, model_name: str = "mistral"):
        self.model_name = model_name
        self.timeout = OLLAMA_TIMEOUT
        self.max_retries = OLLAMA_MAX_RETRIES
        
        # Create client once and reuse (optimization: connection reuse)
        self.client = ollama.Client(timeout=self.timeout)
        logger.info(f"Initialized Generator with model={model_name}, timeout={self.timeout}s")

    def _truncate_chunk(self, text: str, max_chars: int = MAX_CHUNK_CHARS) -> str:
        """Truncate a chunk to max_chars, preserving word boundaries."""
        if len(text) <= max_chars:
            return text
        
        # Find last space before limit to avoid cutting words
        truncated = text[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.7:  # Only use if reasonable position
            truncated = truncated[:last_space]
        
        return truncated.rstrip() + "..."

    def _build_context(self, context: List[Dict[str, Any]]) -> str:
        """
        Build context string with budget controls.
        
        Strategy:
        1. Truncate each chunk to MAX_CHUNK_CHARS
        2. Add chunks in order until MAX_CONTEXT_CHARS reached
        3. Preserve source attribution
        """
        context_parts = []
        total_chars = 0
        included_count = 0
        
        for c in context:
            chunk_text = c.get("text", "")
            chunk_id = c.get("id", "unknown")[:16]  # Shortened ID for readability
            
            # Get source info for better citations
            metadata = c.get("metadata", {})
            source_file = metadata.get("filename", "")
            
            # Truncate individual chunk
            truncated = self._truncate_chunk(chunk_text, MAX_CHUNK_CHARS)
            
            # Build formatted chunk
            if source_file:
                formatted = f"[Source: {source_file} | {chunk_id}]\n{truncated}"
            else:
                formatted = f"[Source: {chunk_id}]\n{truncated}"
            
            # Check budget
            if total_chars + len(formatted) > MAX_CONTEXT_CHARS:
                # Log if we're dropping chunks
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
        
        return "\n\n".join(context_parts)

    def _generate_internal(self, query: str, context: List[Dict[str, Any]]) -> str:
        """Internal generation method that makes the actual Ollama call."""
        # Build context with budget controls
        context_text = self._build_context(context)

        system_prompt = (
            "You are a precise technical assistant. Answer the question using ONLY the provided context. "
            "If the answer is not in the context, say 'I cannot answer this based on the provided documents.' "
            "Cite your sources using the format [Source: filename | chunk_id]. "
            "Do not hallucinate external information."
        )

        user_prompt = f"Context:\n{context_text}\n\nQuestion: {query}"

        logger.info(f"Sending prompt to Ollama ({self.model_name}), context: {len(context_text)} chars")
        
        # Reuse persistent client (optimization)
        response = self.client.chat(
            model=self.model_name,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ]
        )
        return response['message']['content']

    @trace("generate")
    def generate(self, query: str, context: List[Dict[str, Any]]) -> str:
        """
        Generates an answer using the context with retry logic and timeout handling.
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                return self._generate_internal(query, context)
            
            except ollama.ResponseError as e:
                # Ollama returned an error response
                logger.error(f"Ollama response error (attempt {attempt + 1}/{self.max_retries}): {e}")
                last_error = f"Ollama error: {e.error if hasattr(e, 'error') else str(e)}"
                # Don't retry on model not found or similar client errors
                if hasattr(e, 'status_code') and e.status_code in (400, 404):
                    return f"Error: Model '{self.model_name}' not found or invalid request. {last_error}"
            
            except ConnectionError as e:
                # Cannot connect to Ollama server
                logger.error(f"Connection error (attempt {attempt + 1}/{self.max_retries}): {e}")
                last_error = "Cannot connect to Ollama server"
            
            except TimeoutError as e:
                # Request timed out
                logger.error(f"Timeout error (attempt {attempt + 1}/{self.max_retries}): {e}")
                last_error = f"Request timed out after {self.timeout}s"
            
            except Exception as e:
                # Handle httpx/httpcore timeout exceptions
                error_type = type(e).__name__
                error_msg = str(e)
                
                if "timeout" in error_type.lower() or "timeout" in error_msg.lower():
                    logger.error(f"Timeout (attempt {attempt + 1}/{self.max_retries}): {error_type}: {e}")
                    last_error = f"Request timed out after {self.timeout}s"
                elif "connect" in error_type.lower() or "connect" in error_msg.lower():
                    logger.error(f"Connection error (attempt {attempt + 1}/{self.max_retries}): {error_type}: {e}")
                    last_error = "Cannot connect to Ollama server"
                else:
                    logger.error(f"Unexpected error (attempt {attempt + 1}/{self.max_retries}): {error_type}: {e}")
                    last_error = f"{error_type}: {error_msg}"
            
            # Exponential backoff before retry (1s, 2s, 4s)
            if attempt < self.max_retries - 1:
                wait_time = 2 ** attempt
                logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
        
        # All retries exhausted
        logger.error(f"Generation failed after {self.max_retries} attempts")
        
        if "connect" in (last_error or "").lower():
            return f"Error: {last_error}. Is 'ollama serve' running?"
        elif "timeout" in (last_error or "").lower():
            return f"Error: {last_error}. The model may be overloaded or the query too complex."
        else:
            return f"Error after {self.max_retries} attempts: {last_error}"
