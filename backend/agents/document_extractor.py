"""
Document extraction utilities.
Supports PDF files and plain text files.
"""
from __future__ import annotations
import io
from typing import Optional

from fastapi import UploadFile


async def extract_text_from_upload(file: UploadFile) -> str:
    """
    Extract readable text from an uploaded file.
    Supports: .pdf, .txt, .md, and any plain-text format.
    """
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".pdf"):
        return _extract_from_pdf(content)
    else:
        # Treat as plain text (txt, md, etc.)
        return _extract_from_text(content)


def _extract_from_pdf(content: bytes) -> str:
    """Use pypdf to extract text from PDF bytes."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        extracted = "\n\n".join(pages)
        if not extracted.strip():
            return "[PDF uploaded but no readable text could be extracted — try a text-based PDF]"
        return extracted
    except Exception as e:
        return f"[PDF extraction failed: {e}]"


def _extract_from_text(content: bytes) -> str:
    """Decode plain text, trying common encodings."""
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")
