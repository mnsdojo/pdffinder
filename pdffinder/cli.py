import os
import typer
from typing import Optional
from rich.console import Console
from rich.table import Table
from .search import search_pdfs
from .downloader import download_pdf, download_batch
from .scanner import scan_url_safety, scan_pdf_file

app = typer.Typer(help="PDF Finder — search, download, and scan PDFs from the web.")
console = Console()


@app.command()
def search(
    query: str = typer.Argument(..., help="Topic to search PDFs for"),
    max_results: int = typer.Option(10, "--max", "-m", help="Maximum results"),
    download_dir: str = typer.Option("./downloads", "--dir", "-d", help="Download directory"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Select results to download"),
):
    """Search for PDFs, scan URLs, and optionally download interactively."""
    console.print(f"\n[bold blue]Searching for:[/] {query}\n")

    results = search_pdfs(query, max_results=max_results)
    if not results:
        console.print("[red]No PDFs found.[/]")
        raise typer.Exit()

    table = Table(title=f"Found {len(results)} PDFs")
    table.add_column("#", style="dim")
    table.add_column("Title", width=40)
    table.add_column("Safety", width=12)
    table.add_column("URL", width=50)

    safe_results = []
    for i, r in enumerate(results, 1):
        safety = scan_url_safety(r["url"])
        label = {
            "safe": "[green]Safe[/]",
            "suspicious": "[yellow]Suspicious[/]",
            "unknown": "[dim]Unknown[/]",
        }.get(safety, "[dim]Unknown[/]")
        table.add_row(str(i), r["title"][:60], label, r["url"][:60])
        safe_results.append({**r, "safety": safety})

    console.print(table)

    if interactive and safe_results:
        _handle_interactive(safe_results, download_dir)


def _handle_interactive(results: list[dict], download_dir: str):
    import questionary

    choices = []
    for i, r in enumerate(results):
        safety_icon = {"safe": "🟢", "suspicious": "🟡", "unknown": "⚪"}.get(r["safety"], "⚪")
        label = f"{safety_icon} {r['title'][:70]}"
        choices.append(questionary.Choice(title=label, value=i, checked=False))

    selected_indices = questionary.checkbox(
        "Select PDFs to download (↑↓ navigate, Space toggle, Enter confirm):",
        choices=choices,
    ).ask()

    if not selected_indices:
        console.print("[dim]Skipping download.[/]")
        return

    selected = [results[i] for i in selected_indices]
    console.print(f"\n[bold]Downloading {len(selected)} PDF(s) to {download_dir}...[/]\n")

    for r in selected:
        console.print(f"\n[cyan]Downloading:[/] {r['title'][:60]}")
        dl_result = download_pdf(r["url"], output_dir=download_dir)
        if dl_result:
            scan_result = scan_pdf_file(dl_result["path"])
            console.print(f"  [green]Saved:[/] {dl_result['path']} ({dl_result['size']} bytes)")
            status = "[green]Clean[/]" if "no issues" in scan_result["summary"].lower() else "[yellow]Issues found[/]"
            console.print(f"  Scan: {status} — {scan_result['summary']}")


@app.command()
def download(
    url: str = typer.Argument(..., help="PDF URL to download"),
    output: str = typer.Option("", "--output", "-o", help="Output filename"),
    dir: str = typer.Option("./downloads", "--dir", "-d", help="Download directory"),
):
    """Download a single PDF and scan it."""
    result = download_pdf(url, output_dir=dir, output_name=output)
    if not result:
        console.print("[red]Download failed.[/]")
        raise typer.Exit()

    filepath = result["path"]
    console.print(f"[green]Downloaded:[/] {filepath} ({result['size']} bytes)")

    scan_result = scan_pdf_file(filepath)
    console.print(f"[bold]Scan result:[/] {scan_result['summary']}")
    if scan_result["issues"]:
        for issue in scan_result["issues"]:
            console.print(f"  [yellow]{issue}[/]")


@app.command()
def batch(
    urls: Optional[list[str]] = typer.Argument(None, help="One or more PDF URLs"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="File with URLs (one per line)"),
    dir: str = typer.Option("./downloads", "--dir", "-d", help="Download directory"),
):
    """Download multiple PDFs and scan each one."""
    all_urls: list[str] = []

    if file:
        try:
            with open(file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        all_urls.append(line)
        except FileNotFoundError:
            console.print(f"[red]File not found: {file}[/]")
            raise typer.Exit()
        except Exception as e:
            console.print(f"[red]Error reading file: {e}[/]")
            raise typer.Exit()

    if urls:
        all_urls.extend(urls)

    if not all_urls:
        console.print("[red]Provide URLs as arguments or via --file.[/]")
        raise typer.Exit()

    console.print(f"\n[bold]Downloading {len(all_urls)} PDF(s) to {dir}...[/]\n")
    results = download_batch(all_urls, output_dir=dir)

    console.print(f"\n[bold]Scanning {len(results)} downloaded PDF(s)...[/]")
    clean = 0
    for r in results:
        scan_result = scan_pdf_file(r["path"])
        if "no issues" in scan_result["summary"].lower():
            clean += 1
            console.print(f"  [green]Clean:[/] {os.path.basename(r['path'])}")
        else:
            console.print(f"  [yellow]Issues:[/] {os.path.basename(r['path'])} — {scan_result['summary']}")

    console.print(f"\n[bold]Summary:[/] {len(results)} downloaded, {clean} clean, {len(results) - clean} with issues")


@app.command()
def scan(
    filepath: str = typer.Argument(..., help="Path to PDF file"),
):
    """Scan a local PDF for safety issues."""
    if not os.path.exists(filepath):
        console.print(f"[red]File not found: {filepath}[/]")
        raise typer.Exit()

    result = scan_pdf_file(filepath)
    console.print(f"[bold]Scan result:[/] {result['summary']}")
    if result["issues"]:
        for issue in result["issues"]:
            console.print(f"  [yellow]{issue}[/]")
    if result.get("metadata"):
        console.print("\n[bold]Metadata:[/]")
        for k, v in result["metadata"].items():
            console.print(f"  {k}: {v}")


@app.command()
def info(
    filepath: str = typer.Argument(..., help="Path to PDF file"),
):
    """Show PDF metadata and file info (quick, no deep scan)."""
    if not os.path.exists(filepath):
        console.print(f"[red]File not found: {filepath}[/]")
        raise typer.Exit()

    from .scanner import compute_file_hash

    file_size = os.path.getsize(filepath)
    hashes = compute_file_hash(filepath)

    console.print(f"[bold]File:[/] {filepath}")
    console.print(f"  Size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")

    if hashes.get("sha256"):
        console.print(f"  SHA256: {hashes['sha256']}")
    if hashes.get("md5"):
        console.print(f"  MD5: {hashes['md5']}")

    try:
        from pypdf import PdfReader
        reader = PdfReader(filepath)
        meta = reader.metadata or {}
        console.print(f"\n[bold]PDF Metadata:[/]")
        console.print(f"  Pages: {len(reader.pages)}")
        console.print(f"  Encrypted: {reader.is_encrypted}")
        for k, v in vars(meta).items():
            if v and not k.startswith("_"):
                console.print(f"  {k.strip('/').lower()}: {v}")
    except ImportError:
        console.print("[dim]pypdf not installed — PDF metadata unavailable[/]")
    except Exception as e:
        console.print(f"[red]Error reading PDF: {e}[/]")


if __name__ == "__main__":
    app()
