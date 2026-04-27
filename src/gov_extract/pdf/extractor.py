"""Extract per-page text from a PDF using pdfminer.six."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import structlog
from pdfminer.high_level import extract_text_to_fp
from pdfminer.layout import LAParams

logger = structlog.get_logger()


def extract_pages(pdf_path: Path) -> dict[int, str]:
    """Extract text from every page of a PDF.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Dict mapping 1-indexed page number to extracted text.
    """
    pages: dict[int, str] = {}
    laparams = LAParams(line_margin=0.5, word_margin=0.1)

    with open(pdf_path, "rb") as f:
        page_num = 1
        while True:
            buf = StringIO()
            try:
                extract_text_to_fp(
                    f,
                    buf,
                    laparams=laparams,
                    page_numbers={page_num - 1},  # 0-indexed in pdfminer
                    output_type="text",
                    codec="utf-8",
                )
                text = buf.getvalue()
                if not text and page_num > 1:
                    break
                pages[page_num] = text
                page_num += 1
                f.seek(0)
            except Exception:
                break

    logger.info("pdf_extracted", path=str(pdf_path), pages=len(pages))
    return pages


def extract_pages_bulk(pdf_path: Path) -> dict[int, str]:
    """Extract all pages at once using pdfminer page iterator (preferred for speed).

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Dict mapping 1-indexed page number to extracted text.
    """
    from pdfminer.high_level import extract_pages as _extract_pages
    from pdfminer.layout import LTTextContainer

    pages: dict[int, str] = {}
    laparams = LAParams(line_margin=0.5, word_margin=0.1)

    for page_num, page_layout in enumerate(_extract_pages(str(pdf_path), laparams=laparams), 1):
        text_parts: list[str] = []
        for element in page_layout:
            if isinstance(element, LTTextContainer):
                text_parts.append(element.get_text())
        pages[page_num] = "".join(text_parts)

    logger.info("pdf_extracted", path=str(pdf_path), pages=len(pages))
    return pages
