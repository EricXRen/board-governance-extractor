"""Load a PDF from a local path or HTTPS URL, caching remote downloads."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import structlog

logger = structlog.get_logger()


def load_pdf(path_or_url: str, cache_dir: str = "~/.gov_extract/cache") -> Path:
    """Return a local Path to the PDF, downloading if necessary.

    Args:
        path_or_url: Local file path or HTTPS URL.
        cache_dir: Directory for caching remote downloads.

    Returns:
        Resolved local Path to the PDF file.

    Raises:
        FileNotFoundError: If a local path does not exist.
        httpx.HTTPError: If the remote download fails.
    """
    if path_or_url.startswith("https://") or path_or_url.startswith("http://"):
        return _download(path_or_url, Path(cache_dir).expanduser())

    local = Path(path_or_url).resolve()
    if not local.exists():
        raise FileNotFoundError(f"PDF not found: {local}")
    return local


def _download(url: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
    filename = url.rsplit("/", 1)[-1].split("?")[0] or "download.pdf"
    cached = cache_dir / f"{url_hash}_{filename}"

    if cached.exists():
        logger.info("pdf_cache_hit", url=url, cached=str(cached))
        return cached

    logger.info("pdf_downloading", url=url)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        response = client.get(url)
        response.raise_for_status()
        cached.write_bytes(response.content)

    logger.info("pdf_downloaded", url=url, size=cached.stat().st_size, cached=str(cached))
    return cached
