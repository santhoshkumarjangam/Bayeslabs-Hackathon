"""
document_service.py — Document upload, storage, and retrieval service.

Provides:
  POST /documents/upload  — Upload a PDF/.txt file, extract text, store in DB
  GET  /documents         — List all documents (metadata only)
  GET  /documents/{id}    — Get a document with its full extracted text
  DELETE /documents/{id}  — Remove a document
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.document_extractor import extract_text_from_upload
from database import get_db
from models import DocumentRecord

router = APIRouter(prefix="/documents", tags=["Documents"])


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic response schemas
# ─────────────────────────────────────────────────────────────────────────────

class DocumentMeta(BaseModel):
    """Lightweight metadata — returned in list views."""
    id: str
    filename: str
    file_type: str
    char_count: int
    word_count: int
    uploaded_at: str
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class DocumentDetail(DocumentMeta):
    """Full document including raw text — returned on single-doc fetch."""
    raw_text: str


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentDetail, status_code=201)
async def upload_document(
    file: UploadFile = File(..., description="PDF or plain-text file (.pdf, .txt, .md)"),
    description: Optional[str] = Form(
        default=None,
        description="Optional label, e.g. 'Chapter 3 notes' or 'Syllabus'"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a document. The raw text is extracted and stored in the database.

    Returns a `document_id` you can pass to `POST /start` to use this
    document's content as the basis for a study session — no need to re-upload.
    """
    filename = file.filename or "untitled"
    allowed = (".pdf", ".txt", ".md", ".text")
    if not any(filename.lower().endswith(ext) for ext in allowed):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed)}",
        )

    raw_text = await extract_text_from_upload(file)

    if not raw_text.strip() or raw_text.startswith("[PDF extraction failed"):
        raise HTTPException(
            status_code=422,
            detail=f"Could not extract readable text from '{filename}'. "
                   "Try a text-based PDF or a .txt file.",
        )

    # Determine file type
    file_type = "pdf" if filename.lower().endswith(".pdf") else "text"

    # Persist to DB
    doc = DocumentRecord(
        filename=filename,
        file_type=file_type,
        raw_text=raw_text,
        char_count=len(raw_text),
        word_count=len(raw_text.split()),
        description=description,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return DocumentDetail(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        char_count=doc.char_count,
        word_count=doc.word_count,
        uploaded_at=doc.uploaded_at.isoformat(),
        description=doc.description,
        raw_text=doc.raw_text,
    )


@router.get("", response_model=List[DocumentMeta])
async def list_documents(db: AsyncSession = Depends(get_db)):
    """List all uploaded documents (metadata only, no raw text)."""
    result = await db.execute(
        select(DocumentRecord).order_by(DocumentRecord.uploaded_at.desc())
    )
    docs = result.scalars().all()
    return [
        DocumentMeta(
            id=d.id,
            filename=d.filename,
            file_type=d.file_type,
            char_count=d.char_count,
            word_count=d.word_count,
            uploaded_at=d.uploaded_at.isoformat(),
            description=d.description,
        )
        for d in docs
    ]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve a document by ID, including its extracted text."""
    result = await db.execute(
        select(DocumentRecord).where(DocumentRecord.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentDetail(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        char_count=doc.char_count,
        word_count=doc.word_count,
        uploaded_at=doc.uploaded_at.isoformat(),
        description=doc.description,
        raw_text=doc.raw_text,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a document from the database."""
    result = await db.execute(
        select(DocumentRecord).where(DocumentRecord.id == document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    await db.delete(doc)
    await db.commit()
