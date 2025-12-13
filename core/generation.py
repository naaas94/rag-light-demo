import ollama
from typing import List, Dict, Any
from core.logging_config import logger
from core.observability import trace

class Generator:
    def __init__(self, model_name: str = "mistral"):
        self.model_name = model_name

    @trace("generate")
    def generate(self, query: str, context: List[Dict[str, Any]]) -> str:
        """
        Generates an answer using the context.
        """
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

        try:
            logger.info(f"Sending prompt to Ollama ({self.model_name})...")
            response = ollama.chat(model=self.model_name, messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ])
            return response['message']['content']
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            return "Error calling Ollama. Is 'ollama serve' running?"
