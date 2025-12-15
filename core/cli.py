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
from core.retrieval import Retriever
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
    # Initialize store (this will create persistence dir)
    vector_store = VectorStore()
    lexical_index = LexicalIndex()
    
    vector_store.upsert(chunks)
    lexical_index.build(chunks, incremental=not validated.reset)
    
    elapsed = time.time() - start_time
    console.print(f"[bold green]Ingestion complete in {elapsed:.2f}s[/bold green]")
    console.print(f"Docs: {len(docs)}, Chunks: {len(chunks)}")


@app.command()
def query(
    question: str,
    top_k: int = typer.Option(5, help="Number of context chunks to retrieve"),
    mode: str = typer.Option("hybrid", help="Retrieval mode: dense, lexical, hybrid"),
    model: str = typer.Option("mistral", help="Ollama model to use")
):
    """
    Queries the RAG system.
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
    
    # 1. Retrieve
    try:
        vector_store = VectorStore()
        lexical_index = LexicalIndex()
        retriever = Retriever(vector_store, lexical_index)
    except Exception as e:
        console.print(f"[red]Failed to initialize retriever: {e}[/red]")
        console.print("[yellow]Hint: Run 'ingest' first to create the indices.[/yellow]")
        raise typer.Exit(1)
    
    console.print(f"[bold blue]Question:[/bold blue] {validated.question}")
    with console.status("[bold green]Retrieving...[/bold green]"):
        context = retriever.retrieve(validated.question, top_k=validated.top_k, mode=validated.mode)
    
    # Show retrieved context (Telemetry/Observability Lite)
    table = Table(title=f"Retrieved Context (Mode: {validated.mode})")
    table.add_column("Rank", style="cyan", width=5)
    table.add_column("Source", style="magenta")
    table.add_column("Score", style="green")
    table.add_column("Snippet", style="white")
    
    for i, c in enumerate(context):
        table.add_row(
            str(i + 1), 
            c['metadata'].get('filename', 'unknown'), 
            f"{c.get('score', 0):.4f}", 
            c['text'][:100] + "..."
        )
    console.print(table)

    # 2. Generate
    generator = Generator(model_name=validated.model)
    with console.status(f"[bold green]Generating Answer ({validated.model})...[/bold green]"):
        answer = generator.generate(validated.question, context)
    
    console.print(Panel(answer, title="[bold yellow]Answer[/bold yellow]"))
    
    total_time = time.time() - start_time
    console.print(f"[dim]Total time: {total_time:.2f}s[/dim]")
    
    telemetry.flush()
    console.print(f"[dim]Trace saved to logs/trace_{trace_id}.jsonl[/dim]")


@app.command()
def eval(
    dataset_path: str = typer.Option("data/eval/questions.jsonl", help="Path to evaluation dataset"),
    top_k: int = typer.Option(5, help="Number of chunks to retrieve per question")
):
    """
    Runs the offline evaluation harness (HitRate@K) using phrase matching.
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
    
    # Initialize Retriever
    try:
        vector_store = VectorStore()
        lexical_index = LexicalIndex()
        retriever = Retriever(vector_store, lexical_index)
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
        
    console.print(table)
    
    hit_rate = hits / total if total > 0 else 0
    console.print(Panel(f"[bold]Overall Hit Rate@{top_k}: {hit_rate:.2%}[/bold]", style="blue"))


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
    
    # Summary
    if all_ok:
        console.print("\n[bold green]All checks passed![/bold green]")
    else:
        console.print("\n[bold yellow]Some checks failed. See above for details.[/bold yellow]")


@app.command()
def serve():
    console.print("[yellow]FastAPI server not yet implemented in this PoC step.[/yellow]")


if __name__ == "__main__":
    app()
