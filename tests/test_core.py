import pytest
import os
import shutil
from core.models import Document, Chunk
from core.ingest import Chunker, Loader

def test_stable_id():
    doc1 = Document.compute_id("file1.txt", "content")
    doc2 = Document.compute_id("file1.txt", "content")
    assert doc1 == doc2

    chunk1 = Chunk.compute_id(doc1, "text", 0, 4)
    chunk2 = Chunk.compute_id(doc1, "text", 0, 4)
    assert chunk1 == chunk2

def test_chunking_determinism():
    chunker = Chunker(chunk_size=10, chunk_overlap=0)
    text = "hello world this is a test"
    # Logic in chunker is simple split for now, let's verify it doesn't crash
    # and returns consistent results
    splits = chunker.split_text(text)
    assert len(splits) > 0
    assert splits[0]["text"] == "hello " # Breaks at space

    # Re-run
    splits2 = chunker.split_text(text)
    assert splits == splits2

def test_loader_missing_dir(tmp_path):
    loader = Loader()
    # Should just return empty or log error, not crash
    docs = list(loader.load(str(tmp_path / "missing")))
    assert len(docs) == 0
