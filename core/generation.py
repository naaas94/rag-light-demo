import os
import time
import ollama
from typing import List, Dict, Any
from core.logging_config import logger
from core.observability import trace

# Configuration via environment variables
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "120"))  # seconds
OLLAMA_MAX_RETRIES = int(os.environ.get("OLLAMA_MAX_RETRIES", "3"))


class Generator:
    def __init__(self, model_name: str = "mistral"):
        self.model_name = model_name
        self.timeout = OLLAMA_TIMEOUT
        self.max_retries = OLLAMA_MAX_RETRIES

    def _generate_internal(self, query: str, context: List[Dict[str, Any]]) -> str:
        """Internal generation method that makes the actual Ollama call."""
        context_text = "\n\n".join([
            f"[Source: {c['id']}]\n{c['text']}" 
            for c in context
        ])

        system_prompt = (
            "You are a precise technical assistant. Answer the question using ONLY the provided context. "
            "If the answer is not in the context, say 'I cannot answer this based on the provided documents.' "
            "Cite your sources using the format [Source: chunk_id]. "
            "Do not hallucinate external information."
        )

        user_prompt = f"Context:\n{context_text}\n\nQuestion: {query}"

        logger.info(f"Sending prompt to Ollama ({self.model_name})...")
        
        # Create client with timeout configuration
        client = ollama.Client(timeout=self.timeout)
        
        response = client.chat(
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
