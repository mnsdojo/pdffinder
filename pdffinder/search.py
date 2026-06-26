import re
import requests

DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

def search_pdfs(query: str, max_results: int = 10) -> list[dict]:
    """Search for PDFs using DuckDuckGo Lite (no extra deps needed).
    
    Uses the lightweight DuckDuckGo Lite endpoint which returns
    simple HTML — no lxml/bs4 required.
    """
    results = []
    search_query = f"{query} filetype:pdf"

    try:
        resp = requests.post(
            DDG_LITE_URL,
            data={"q": search_query},
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PDFinder/1.0)",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException:
        return results

    html = resp.text

    # DuckDuckGo Lite returns results as <a> tags within table rows
    # Each result has: rank, then <a href="...">title</a>, then snippet text
    # We match sequential patterns: URL in href, title text, snippet text
    
    links = re.findall(
        r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        html,
        re.DOTALL,
    )

    # Extract snippets — they appear after closing </a> tag, before next <tr>
    snippets_raw = re.split(r'<a[^>]*href="https?://[^"]+"[^>]*>.*?</a>', html)

    seen = set()
    for i, (url, title_raw) in enumerate(links):
        if len(results) >= max_results:
            break
        
        title = re.sub(r"<[^>]+>", "", title_raw).strip()
        if not url.lower().endswith(".pdf"):
            continue
        if url in seen:
            continue
        seen.add(url)

        # Get snippet from the text following this link
        snippet = ""
        if i + 1 < len(snippets_raw):
            snippet_text = snippets_raw[i + 1]
            # Get text between this snippet and next <tr> or end
            snippet_match = re.search(r"(.*?)(?:<tr|$)", snippet_text, re.DOTALL)
            if snippet_match:
                snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip()
                snippet = re.sub(r"\s+", " ", snippet)[:200]

        results.append({
            "title": title or "Untitled",
            "url": url,
            "snippet": snippet,
        })

    return results




