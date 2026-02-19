"""Text processing utilities — HTML stripping, normalization."""

import hashlib
import re

from bs4 import BeautifulSoup


def strip_html(html: str) -> str:
    """Remove HTML tags and return plain text."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(separator=" ", strip=True)


def normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def hash_string(text: str) -> str:
    """SHA256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def title_company_hash(title: str, company: str) -> str:
    """Generate a deduplication hash from normalized title + company."""
    normalized = normalize_text(title) + "|" + normalize_text(company)
    return hash_string(normalized)


def url_hash(url: str) -> str:
    """Generate a hash from a normalized URL."""
    # Strip trailing slashes and query params for normalization
    clean = url.strip().rstrip("/").split("?")[0].split("#")[0].lower()
    return hash_string(clean)


def truncate(text: str, max_length: int = 3000) -> str:
    """Truncate text to max_length characters, ending at a word boundary."""
    if not text or len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.8:
        truncated = truncated[:last_space]
    return truncated + "..."
