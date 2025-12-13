import typer
import os
import time
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from typing import Optional
from core.ingest import Loader, Chunker
from core.store import VectorStore, LexicalIndex
from core.retrieval import Retriever
from core.generation import Generator
from core.logging_config import logger
from core.observability import telemetry

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
    console.print(Panel(f"[bold green]Starting Ingestion from {data_dir}[/bold green]"))
    
    start_time = time.time()
    
    # 1. Load
    loader = Loader()
    docs = list(loader.load(data_dir))
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
    lexical_index.build(chunks)
    
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
    trace_id = telemetry.start_trace()
    console.print(f"[dim]Trace ID: {trace_id}[/dim]")
    
    start_time = time.time()
    
    # 1. Retrieve
    vector_store = VectorStore()
    lexical_index = LexicalIndex()
    retriever = Retriever(vector_store, lexical_index)
    
    console.print(f"[bold blue]Question:[/bold blue] {question}")
    with console.status("[bold green]Retrieving...[/bold green]"):
        context = retriever.retrieve(question, top_k=top_k, mode=mode)
    
    # Show retrieved context (Telemetry/Observability Lite)
    table = Table(title=f"Retrieved Context (Mode: {mode})")
    table.add_column("Rank", style="cyan", width=5)
    table.add_column("Source", style="magenta")
    table.add_column("Score", style="green")
    table.add_column("Snippet", style="white")
    
    for i, c in enumerate(context):
        table.add_row(
            str(i+1), 
            c['metadata'].get('filename', 'unknown'), 
            f"{c.get('score', 0):.4f}", 
            c['text'][:100] + "..."
        )
    console.print(table)

    # 2. Generate
    generator = Generator(model_name=model)
    with console.status(f"[bold green]Generating Answer ({model})...[/bold green]"):
        answer = generator.generate(question, context)
    
    console.print(Panel(answer, title="[bold yellow]Answer[/bold yellow]"))
    
    total_time = time.time() - start_time
    console.print(f"[dim]Total time: {total_time:.2f}s[/dim]")
    
    telemetry.flush()
    console.print(f"[dim]Trace saved to logs/trace_{trace_id}.jsonl[/dim]")

@app.command()
def serve():
    console.print("[yellow]FastAPI server not yet implemented in this PoC step.[/yellow]")

if __name__ == "__main__":
    app()
