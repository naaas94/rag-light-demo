"""
CLI interface for the RAG system.

Optimized to use RAGService singleton for shared resources.
"""

import typer
import os
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from typing import Optional
from pydantic import ValidationError

from core.ingest import Loader, Chunker
from core.store import VectorStore, LexicalIndex
from core.service import RAGService
from core.generation import Generator
from core.logging_config import logger
from core.observability import telemetry
from core.models import QueryInput, IngestInput

app = typer.Typer()
console = Console()


@app.command()
def ingest(
    data_dir: str = typer.Option("data/corpus", help="Directory to ingest files from"),
    reset: bool = typer.Option(False, help="Reset the index before ingesting")
):
    """
    Ingests documents from the data directory into ChromaDB and BM25.
    """
    # Validate inputs
    try:
        validated = IngestInput(data_dir=data_dir, reset=reset)
    except ValidationError as e:
        console.print(f"[red]Invalid input: {e}[/red]")
        raise typer.Exit(1)
    
    console.print(Panel(f"[bold green]Starting Ingestion from {validated.data_dir}[/bold green]"))
    
    # Handle reset flag
    if validated.reset:
        import shutil
        if os.path.exists("chroma_db"):
            shutil.rmtree("chroma_db")
            console.print("[yellow]Removed ChromaDB directory[/yellow]")
        if os.path.exists("bm25_index.pkl"):
            os.remove("bm25_index.pkl")
            console.print("[yellow]Removed BM25 index[/yellow]")
        console.print("[bold]Index reset complete[/bold]")
        
        # Reset the RAGService singleton to pick up fresh indices
        RAGService.reset_instance()
    
    start_time = time.time()
    
    # 1. Load
    loader = Loader()
    docs = list(loader.load(validated.data_dir))
    if not docs:
        console.print("[red]No documents found![/red]")
        return

    # 2. Chunk
    chunker = Chunker()
    chunks = chunker.chunk(docs)
    
    # 3. Index
    # Use fresh instances for ingest to avoid stale data issues
    vector_store = VectorStore()
    lexical_index = LexicalIndex()
    
    vector_store.upsert(chunks)
    lexical_index.build(chunks, incremental=not validated.reset)
    
    elapsed = time.time() - start_time
    console.print(f"[bold green]Ingestion complete in {elapsed:.2f}s[/bold green]")
    console.print(f"Docs: {len(docs)}, Chunks: {len(chunks)}")
    
    # Reset singleton so next query picks up new data
    RAGService.reset_instance()
    console.print("[dim]RAGService cache cleared for fresh data[/dim]")


@app.command()
def query(
    question: str,
    top_k: int = typer.Option(5, help="Number of context chunks to retrieve"),
    mode: str = typer.Option("hybrid", help="Retrieval mode: dense, lexical, hybrid"),
    model: str = typer.Option("mistral", help="Ollama model to use")
):
    """
    Queries the RAG system.
    
    Uses shared RAGService for optimized performance (resources loaded once).
    """
    # Validate inputs
    try:
        validated = QueryInput(question=question, top_k=top_k, mode=mode, model=model)
    except ValidationError as e:
        console.print(f"[red]Invalid input: {e}[/red]")
        raise typer.Exit(1)
    
    trace_id = telemetry.start_trace()
    console.print(f"[dim]Trace ID: {trace_id}[/dim]")
    
    start_time = time.time()
    
    # Use shared RAGService (optimization: resources loaded once)
    try:
        rag = RAGService.get_instance()
        retriever = rag.retriever
    except Exception as e:
        console.print(f"[red]Failed to initialize retriever: {e}[/red]")
        console.print("[yellow]Hint: Run 'ingest' first to create the indices.[/yellow]")
        raise typer.Exit(1)
    
    console.print(f"[bold blue]Question:[/bold blue] {validated.question}")
    with console.status("[bold green]Retrieving...[/bold green]"):
        retrieve_start = time.time()
        context = retriever.retrieve(validated.question, top_k=validated.top_k, mode=validated.mode)
        retrieve_time = time.time() - retrieve_start
    
    # Show retrieved context (Telemetry/Observability Lite)
    def _format_snippet(text: str, start_char: object, max_len: int = 120) -> str:
        # Collapse newlines / tabs / repeated spaces so the table rendering is stable.
        compact = " ".join((text or "").split())
        # Mark chunks that don't start at the beginning of the document (often mid-sentence due to overlap/windowing).
        if isinstance(start_char, int) and start_char > 0 and compact:
            compact = "__" + compact
        if len(compact) <= max_len:
            return compact
        return compact[:max_len].rstrip() + "..."

    table = Table(title=f"Retrieved Context (Mode: {validated.mode}) [{retrieve_time:.2f}s]")
    table.add_column("Rank", style="cyan", width=5)
    table.add_column("Chunk", style="dim", width=10)
    table.add_column("Source", style="magenta")
    table.add_column("Span", style="dim", width=13)
    table.add_column("Score", style="green")
    table.add_column("Snippet", style="white")
    
    for i, c in enumerate(context):
        md = c.get("metadata") or {}
        start = md.get("start_char")
        end = md.get("end_char")
        span = f"{start}-{end}" if isinstance(start, int) and isinstance(end, int) else "-"
        table.add_row(
            str(i + 1), 
            (c.get("id") or "")[:8],
            c['metadata'].get('filename', 'unknown'), 
            span,
            f"{c.get('score', 0):.4f}", 
            _format_snippet(c.get("text", ""), start)
        )
    console.print(table)

    # 2. Generate (use cached generator from service)
    generator = rag.get_generator(model_name=validated.model)
    with console.status(f"[bold green]Generating Answer ({validated.model})...[/bold green]"):
        generate_start = time.time()
        answer = generator.generate(validated.question, context)
        generate_time = time.time() - generate_start
    
    console.print(Panel(answer, title=f"[bold yellow]Answer[/bold yellow] [{generate_time:.2f}s]"))
    
    total_time = time.time() - start_time
    console.print(f"[dim]Total time: {total_time:.2f}s (retrieve: {retrieve_time:.2f}s, generate: {generate_time:.2f}s)[/dim]")
    
    telemetry.flush()
    console.print(f"[dim]Trace saved to logs/trace_{trace_id}.jsonl[/dim]")


@app.command()
def eval(
    dataset_path: str = typer.Option("data/eval/questions.jsonl", help="Path to evaluation dataset"),
    top_k: int = typer.Option(5, help="Number of chunks to retrieve per question")
):
    """
    Runs the offline evaluation harness (HitRate@K) using phrase matching.
    
    Uses shared RAGService for optimized performance.
    """
    import json
    
    # Basic path validation
    if not dataset_path or not dataset_path.strip():
        console.print("[red]Dataset path cannot be empty[/red]")
        raise typer.Exit(1)
    
    if not os.path.exists(dataset_path):
        console.print(f"[red]Dataset not found at {dataset_path}[/red]")
        raise typer.Exit(1)

    console.print(Panel(f"[bold yellow]Running Evaluation on {dataset_path}[/bold yellow]"))
    
    # Use shared RAGService (optimization)
    try:
        rag = RAGService.get_instance()
        retriever = rag.retriever
    except Exception as e:
        console.print(f"[red]Failed to initialize retriever: {e}[/red]")
        raise typer.Exit(1)
    
    questions = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))
    
    hits = 0
    total = len(questions)
    
    table = Table(title=f"Evaluation Results (k={top_k})")
    table.add_column("Question", style="cyan")
    table.add_column("Expected", style="magenta")
    table.add_column("Found?", style="green")
    
    eval_start = time.time()
    
    for q_item in questions:
        query_text = q_item["question"]
        expected_phrases = [p.lower() for p in q_item["expected_phrases"]]
        
        # Retrieve
        results = retriever.retrieve(query_text, top_k=top_k)
        
        # Check for Hit
        # A hit is if ANY retrieved chunk contains ANY of the expected phrases
        found = False
        retrieved_texts = [r["text"].lower() for r in results]
        
        for phrase in expected_phrases:
            for text in retrieved_texts:
                if phrase in text:
                    found = True
                    break
            if found:
                break
        
        if found:
            hits += 1
            status = "[bold green]YES[/bold green]"
        else:
            status = "[red]NO[/red]"
            
        table.add_row(query_text, str(expected_phrases), status)
    
    eval_time = time.time() - eval_start
        
    console.print(table)
    
    hit_rate = hits / total if total > 0 else 0
    console.print(Panel(
        f"[bold]Overall Hit Rate@{top_k}: {hit_rate:.2%}[/bold]\n"
        f"[dim]Evaluated {total} questions in {eval_time:.2f}s ({eval_time/max(total,1):.2f}s/query)[/dim]",
        style="blue"
    ))


@app.command()
def check():
    """
    Sanity checks the system state (Disk, DB, Models).
    """
    console.print(Panel("[bold]Running System Sanity Check[/bold]"))
    
    all_ok = True
    
    # 1. Check Data Directory
    if os.path.exists("data/corpus"):
        console.print("[green]✓ Data directory exists[/green]")
    else:
        console.print("[red]✗ Data directory missing (data/corpus)[/red]")
        all_ok = False

    # 2. Check Database
    if os.path.exists("chroma_db"):
        console.print("[green]✓ ChromaDB directory exists[/green]")
        try:
            vs = VectorStore()
            count = vs.collection.count()
            console.print(f"  [dim]Collection has {count} vectors[/dim]")
        except Exception as e:
            console.print(f"  [yellow]Could not check collection: {e}[/yellow]")
    else:
        console.print("[yellow]! ChromaDB not found (Run 'ingest' first)[/yellow]")

    # 3. Check BM25
    if os.path.exists("bm25_index.pkl"):
        console.print("[green]✓ BM25 Index exists[/green]")
        try:
            li = LexicalIndex()
            li.load()
            console.print(f"  [dim]Index has {len(li.chunk_map)} chunks[/dim]")
        except ValueError as e:
            console.print(f"  [red]✗ BM25 signature verification failed: {e}[/red]")
            all_ok = False
        except Exception as e:
            console.print(f"  [yellow]Could not load index: {e}[/yellow]")
    else:
        console.print("[yellow]! BM25 Index not found[/yellow]")

    # 4. Check Ollama Connectivity
    try:
        import requests
        # Ollama default port 11434
        resp = requests.get("http://localhost:11434/", timeout=5)
        if resp.status_code == 200:
            console.print("[green]✓ Ollama is running[/green]")
        else:
            console.print(f"[red]✗ Ollama returned status {resp.status_code}[/red]")
            all_ok = False
    except Exception:
        console.print("[red]✗ Could not connect to Ollama (Is 'ollama serve' running?)[/red]")
        all_ok = False
    
    # 5. Check Cache Status
    try:
        from core.embedding import Embedder
        cache_stats = Embedder.get_cache_stats()
        console.print("[green]✓ Embedding cache configured[/green]")
        console.print(f"  [dim]Models loaded: {cache_stats.get('models_loaded', [])}")
        console.print(f"  [dim]Disk cache: {'enabled' if cache_stats.get('disk_cache_enabled') else 'disabled'}[/dim]")
        if cache_stats.get('disk_cache_size') is not None:
            console.print(f"  [dim]Cache entries: {cache_stats.get('disk_cache_size', 0)}[/dim]")
    except Exception as e:
        console.print(f"  [yellow]Could not check cache: {e}[/yellow]")
    
    # Summary
    if all_ok:
        console.print("\n[bold green]All checks passed![/bold green]")
    else:
        console.print("\n[bold yellow]Some checks failed. See above for details.[/bold yellow]")


@app.command()
def serve():
    console.print("[yellow]FastAPI server not yet implemented in this PoC step.[/yellow]")


@app.command()
def cache_stats():
    """
    Display cache statistics for performance monitoring.
    """
    console.print(Panel("[bold]Cache Statistics[/bold]"))
    
    try:
        from core.embedding import Embedder
        stats = Embedder.get_cache_stats()
        
        table = Table(title="Embedding Cache")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        table.add_row("Models Loaded", str(stats.get("models_loaded", [])))
        table.add_row("Disk Cache Enabled", "Yes" if stats.get("disk_cache_enabled") else "No")
        
        if stats.get("disk_cache_size") is not None:
            table.add_row("Disk Cache Entries", str(stats.get("disk_cache_size", 0)))
        if stats.get("disk_cache_volume") is not None:
            volume_mb = stats.get("disk_cache_volume", 0) / (1024 * 1024)
            table.add_row("Disk Cache Size", f"{volume_mb:.2f} MB")
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]Error getting cache stats: {e}[/red]")
    
    # RAGService status
    try:
        from core.service import RAGService
        if RAGService._instance is not None:
            console.print("\n[green]✓ RAGService singleton is active[/green]")
            console.print(f"  [dim]Generators loaded: {list(RAGService._instance._generators.keys())}[/dim]")
            console.print(f"  [dim]BM25 chunks: {len(RAGService._instance.lexical_index.chunk_map)}[/dim]")
        else:
            console.print("\n[yellow]! RAGService not yet initialized (will be on first query)[/yellow]")
    except Exception as e:
        console.print(f"[red]Error checking RAGService: {e}[/red]")


@app.command()
def clear_cache():
    """
    Clear all caches (embedding cache and RAGService singleton).
    """
    console.print(Panel("[bold]Clearing Caches[/bold]"))
    
    try:
        from core.embedding import Embedder
        Embedder.clear_cache()
        console.print("[green]✓ Embedding cache cleared[/green]")
    except Exception as e:
        console.print(f"[red]Error clearing embedding cache: {e}[/red]")
    
    try:
        RAGService.reset_instance()
        console.print("[green]✓ RAGService singleton reset[/green]")
    except Exception as e:
        console.print(f"[red]Error resetting RAGService: {e}[/red]")
    
    console.print("[bold green]Cache cleared successfully[/bold green]")


if __name__ == "__main__":
    app()
