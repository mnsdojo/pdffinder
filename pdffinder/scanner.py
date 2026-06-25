import os
import re
import hashlib
import mimetypes
from urllib.parse import urlparse

SUSPICIOUS_TLDS = {".zip", ".ru", ".su", ".tk", ".ml", ".ga", ".cf", ".gq"}
SUSPICIOUS_KEYWORDS = [
    "free-ebook", "crack", "hack", "warez", "torrent",
    "cracked", "keygen", "patch", "download-free",
]

RAW_SUSPICIOUS_PATTERNS = [
    (r"/JavaScript", "Contains embedded JavaScript"),
    (r"/JS\b", "Contains JavaScript action"),
    (r"/OpenAction", "Has an auto-execute action on open"),
    (r"/AA\b", "Has additional actions (auto-run)"),
    (r"/Launch\b", "Contains launch action (can execute external programs)"),
    (r"/EmbeddedFile", "Contains embedded file(s)"),
    (r"/EmbeddedFiles", "Contains embedded file(s)"),
    (r"/RichMedia", "Contains rich media (Flash, etc.)"),
    (r"/ObjStm", "Uses object streams (often used for obfuscation)"),
    (r"/AcroForm", "Contains interactive form (could be used for data exfiltration)"),
    (r"/Encrypt", "PDF is encrypted"),
    (r"/URI\s*\(.*\)", "Contains URI actions"),
    (r"/SubmitForm", "Contains form submission action"),
    (r"/ImportData", "Contains data import action"),
    (r"/Sound\b", "Contains embedded sound"),
    (r"/Movie\b", "Contains embedded movie"),
]


def compute_file_hash(filepath: str) -> dict[str, str]:
    hashes = {}
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        hashes["sha256"] = hashlib.sha256(data).hexdigest()
        hashes["md5"] = hashlib.md5(data).hexdigest()
    except Exception:
        pass
    return hashes


def scan_url_safety(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return "suspicious"

    domain = parsed.netloc.lower()

    for tld in SUSPICIOUS_TLDS:
        if domain.endswith(tld):
            return "suspicious"

    url_lower = url.lower()
    for kw in SUSPICIOUS_KEYWORDS:
        if kw in url_lower:
            return "suspicious"

    if len(domain) < 5 and "." in domain:
        return "suspicious"

    return "safe"


def scan_pdf_file(filepath: str) -> dict:
    issues = []
    metadata = {}

    if not os.path.exists(filepath):
        return {"summary": "File not found", "issues": ["File does not exist"], "metadata": {}}

    mime_type, _ = mimetypes.guess_type(filepath)
    if mime_type and "pdf" not in mime_type:
        issues.append(f"Unexpected MIME type: {mime_type}")

    file_size = os.path.getsize(filepath)
    if file_size == 0:
        issues.append("File is empty")
        return {"summary": "Empty file", "issues": issues, "metadata": {}}

    if file_size > 100 * 1024 * 1024:
        issues.append(f"Very large file ({file_size / 1024 / 1024:.1f} MB)")

    hashes = compute_file_hash(filepath)
    metadata.update(hashes)

    issues.extend(_scan_raw_pdf(filepath))

    try:
        meta, extra_issues = _analyze_with_pypdf(filepath)
        metadata.update(meta)
        issues.extend(extra_issues)
    except ImportError:
        issues.append("pypdf not installed — deep PDF scan unavailable")
    except Exception as e:
        issues.append(f"PDF parsing error: {e}")

    if not issues:
        summary = "Clean — no issues detected"
    else:
        severities = [i for i in issues if any(kw in i.lower() for kw in
                      ["embedded file", "javascript", "launch", "encrypt",
                       "auto-execute", "object stream", "submitform"])]
        if severities:
            summary = f"{len(issues)} issue(s) found (including {len(severities)} high-severity)"
        else:
            summary = f"{len(issues)} issue(s) found (low severity)"

    return {"summary": summary, "issues": issues, "metadata": metadata}


def _scan_raw_pdf(filepath: str) -> list[str]:
    issues = []

    try:
        with open(filepath, "rb") as f:
            content = f.read()

        text = content.decode("latin-1")

        for pattern, desc in RAW_SUSPICIOUS_PATTERNS:
            if re.search(pattern, text):
                issues.append(desc)

        js_blocks = re.findall(r"<<[^>]*/JavaScript[^>]*>>", text, re.DOTALL)
        js_blocks += re.findall(r"<<[^>]*/JS\b[^>]*>>", text, re.DOTALL)
        seen_obfuscated = False
        for block in js_blocks:
            if re.search(r"(eval|unescape|fromCharCode|String\.fromCharCode)", block, re.IGNORECASE):
                if not seen_obfuscated:
                    issues.append("JavaScript contains obfuscation (eval/unescape)")
                    seen_obfuscated = True

        uri_actions = re.findall(r"/URI\s*\((https?://[^)]+)\)", text)
        if uri_actions:
            for uri in uri_actions:
                parsed = urlparse(uri)
                domain = parsed.netloc.lower()
                is_external = bool(re.match(r'^[a-z0-9.-]+\.[a-z]{2,}', domain))
                if is_external:
                    issues.append(f"External URI action to {domain}")

        uri_count = len(re.findall(r"/URI\s*\([^)]+\)", text))
        if uri_count > 10:
            issues.append(f"High number of external URI actions ({uri_count})")

    except Exception as e:
        issues.append(f"Could not read file: {e}")

    return issues


def _analyze_with_pypdf(filepath: str) -> tuple[dict, list[str]]:
    from pypdf import PdfReader

    issues = []
    metadata = {}

    reader = PdfReader(filepath)
    try:
        meta = reader.metadata
        if meta:
            for k, v in vars(meta).items():
                if v and not k.startswith("_"):
                    key = k.strip("/").lower()
                    metadata[key] = str(v)
    except Exception:
        pass

    metadata["pages"] = len(reader.pages)
    metadata["file_size"] = os.path.getsize(filepath)
    metadata["encrypted"] = reader.is_encrypted

    if reader.is_encrypted:
        issues.append("PDF is encrypted")

    if reader.xmp_metadata:
        try:
            metadata["xmp"] = str(reader.xmp_metadata)[:500]
        except Exception:
            pass

    if reader.pdf_header:
        metadata["pdf_version"] = reader.pdf_header

    for i, page in enumerate(reader.pages):
        try:
            if "/JS" in page.get("/AA", {}) or "/JavaScript" in page.get("/AA", {}):
                issues.append(f"Page {i+1}: auto-execute action found")
        except Exception:
            pass

        try:
            annots = page.get("/Annots")
            if annots:
                for ann in annots:
                    try:
                        obj = ann.get_object()
                        if obj.get("/Subtype") == "/Link":
                            uri = obj.get("/A", {}).get("/URI", "")
                            if uri and not uri.startswith("#"):
                                issues.append(f"Page {i+1}: External link to {uri[:80]}")
                    except Exception:
                        pass
        except Exception:
            pass

    return metadata, issues
