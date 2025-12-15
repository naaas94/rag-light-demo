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
        Recursive character splitter logic with sliding window.
        """
        if not text:
            return []
        
        separators = ["\n\n", "\n", " ", ""]
        chunks = []
        text_len = len(text)
        current_pos = 0
        
        while current_pos < text_len:
            end_pos = min(current_pos + self.chunk_size, text_len)
            
            # If we are not at the end, try to find a natural break point
            if end_pos < text_len:
                found_sep = False
                for sep in separators:
                    if sep == "": continue
                    # Search backwards for a separator from end_pos
                    # Limit search to avoid shrinking chunk too much (e.g. 50%)
                    search_limit = max(current_pos, end_pos - (self.chunk_size // 2))
                    idx = text.rfind(sep, search_limit, end_pos)
                    
                    if idx != -1:
                        # If finding a space, we want to split *at* the space (exclude or include?)
                        # Typically we include the separator in the current chunk or drop it if it's whitespace.
                        # For simple reconstruction, let's include up to the separator.
                        end_pos = idx + len(sep)
                        found_sep = True
                        break
                
                # If no separator found in the allowable range, we force split at chunk_size
                if not found_sep:
                    pass
            
            chunk_text = text[current_pos:end_pos]
            chunks.append({
                "text": chunk_text,
                "start": current_pos,
                "end": end_pos
            })
            
            # Helper to advance position
            # We want the next chunk to start at (end_pos - overlap)
            # BUT we must ensure we actually move forward.
            next_pos = end_pos - self.chunk_overlap
            
            # If overlap pulls us back behind current_pos, that's an infinite loop. 
            # Force at least +1 forward progress (though usually overlap < chunk_size so this is fine).
            if next_pos <= current_pos:
                next_pos = current_pos + 1
            
            # If we reached the end of text, break
            if end_pos == text_len:
                break
                
            current_pos = next_pos
            
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
