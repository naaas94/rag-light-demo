import glob
import os
from typing import List, Generator, Dict, Any
from core.models import Document, Chunk
from core.logging_config import logger

class Loader:
    def __init__(self, extensions: List[str] = [".md", ".txt"]):
        self.extensions = extensions

    def load(self, directory: str) -> Generator[Document, None, None]:
        """Iterates over files in directory matching extensions."""
        logger.info(f"Scanning {directory} for {self.extensions} files...")
        count = 0
        for ext in self.extensions:
            for filepath in glob.glob(os.path.join(directory, "**", f"*{ext}"), recursive=True):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    doc_id = Document.compute_id(filepath, content)
                    doc = Document(
                        id=doc_id,
                        content=content,
                        source=filepath,
                        metadata={"filename": os.path.basename(filepath)}
                    )
                    count += 1
                    yield doc
                except Exception as e:
                    logger.error(f"Failed to load {filepath}: {e}")
        logger.info(f"Loaded {count} documents.")

class Chunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> List[Dict[str, Any]]:
        """
        Simple recursive character splitter logic (simplified).
        Prioritizes splitting on double newlines, then single newlines, then spaces.
        """
        if not text:
            return []
        
        # This is a simplified "recursive" approach
        separators = ["\n\n", "\n", " ", ""]
        final_chunks = []
        
        # Determine strict offsets is tricky with simple split(), so we iterate
        # A more robust implementation would use a token-aware scanner.
        # For this PoC, we will slide a window over words.
        
        # Naive sliding window over words/tokens implementation for robustness
        # to ensure we capture accurate start/end character indices.
        
        # 1. Tokenize (by space for now, to keep it simple but working)
        # Note: In production, use tiktoken or similar.
        words = text.split(" ")
        pass

        # Actually, let's do a character-based sliding window which is safer for offsets
        # but slower. Or just find split points.
        
        current_pos = 0
        text_len = len(text)
        
        chunks = []
        
        while current_pos < text_len:
            end_pos = min(current_pos + self.chunk_size, text_len)
            
            # If we are not at the end, try to find a break point
            if end_pos < text_len:
                # Search backwards for a separator from end_pos
                found_sep = False
                for sep in separators:
                    if sep == "": continue
                    search_limit = max(current_pos, end_pos - (self.chunk_size // 2)) # Don't shrink too much
                    idx = text.rfind(sep, search_limit, end_pos)
                    if idx != -1:
                        end_pos = idx + len(sep) # Include separator in this chunk or next? 
                        # usually better to include it in current or drop it.
                        found_sep = True
                        break
                
                if not found_sep:
                    # Force split
                    pass
            
            chunk_text = text[current_pos:end_pos]
            chunks.append({
                "text": chunk_text,
                "start": current_pos,
                "end": end_pos
            })
            
            # Move forward, subtracting overlap
            current_pos = end_pos - self.chunk_overlap
            
            # Boundary check: ensure we advance
            if current_pos >= end_pos: 
                 current_pos = end_pos # Should not happen if overlap < size
            
            # Correction: if we are stuck at the end
            if current_pos >= text_len:
                break
        
        return chunks

    def chunk(self, documents: List[Document]) -> List[Chunk]:
        all_chunks = []
        for doc in documents:
            splits = self.split_text(doc.content)
            for split in splits:
                chunk_id = Chunk.compute_id(doc.id, split["text"], split["start"], split["end"])
                chunk = Chunk(
                    id=chunk_id,
                    doc_id=doc.id,
                    text=split["text"],
                    start_char=split["start"],
                    end_char=split["end"],
                    metadata=doc.metadata
                )
                all_chunks.append(chunk)
        logger.info(f"Generated {len(all_chunks)} chunks from {len(documents)} documents.")
        return all_chunks
