import os
from typing import Optional
import requests
from urllib.parse import unquote
from rich.progress import Progress, BarColumn, DownloadColumn, TransferSpeedColumn
from rich.console import Console

console = Console()
CHUNK_SIZE = 8192
TIMEOUT = 30


def _extract_filename(url: str) -> str:
    path = unquote(url.split("?")[0].split("#")[0])
    name = os.path.basename(path)
    if not name or not name.endswith(".pdf"):
        name = "document.pdf"
    return name


def download_pdf(
    url: str,
    output_dir: str = "./downloads",
    output_name: str = "",
) -> Optional[dict]:
    os.makedirs(output_dir, exist_ok=True)

    filename = output_name or _extract_filename(url)
    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath):
        console.print(f"[yellow]File exists: {filepath}[/]")
        return {"path": filepath, "size": os.path.getsize(filepath), "url": url}

    try:
        response = requests.get(url, stream=True, timeout=TIMEOUT)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "pdf" not in content_type and "octet-stream" not in content_type:
            if not url.lower().endswith(".pdf"):
                console.print(f"[dim]URL may not be a PDF (content-type: {content_type})[/]")

        total = int(response.headers.get("content-length", 0))

        with Progress(
            "[progress.description]{task.description}",
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"[cyan]Downloading {filename}", total=total)

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))

        actual_size = os.path.getsize(filepath)
        return {"path": filepath, "size": actual_size, "url": url}

    except requests.exceptions.RequestException as e:
        console.print(f"[red]Download failed: {e}[/]")
        if os.path.exists(filepath):
            os.remove(filepath)
        return None


def download_batch(
    urls: list[str],
    output_dir: str = "./downloads",
) -> list[dict]:
    results = []
    for i, url in enumerate(urls, 1):
        console.print(f"\n[bold cyan][{i}/{len(urls)}][/] Downloading: {url[:80]}")
        result = download_pdf(url, output_dir=output_dir)
        if result:
            results.append(result)
            console.print(f"  [green]Saved:[/] {result['path']} ({result['size']} bytes)")
        else:
            console.print(f"  [red]Failed:[/] {url[:80]}")
    return results
