"""
models.py — SQLAlchemy ORM models for the Cramming Crisis Coordinator.

Tables:
  documents         — uploaded files with extracted raw text
  session_documents — many-to-many link: sessions ↔ documents
  session_records   — one per student session (panic state + notes)
  quiz_questions    — MCQs generated for a session
  quiz_submissions  — student answers for a session
  study_plans       — final adaptive plan generated after quiz scoring
  sprint_sessions   — individual sprint blocks within a study plan
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# Document Record
# ─────────────────────────────────────────────────────────────────────────────

class DocumentRecord(Base):
    """
    Uploaded document with extracted raw text.
    Stored once — reusable across multiple study sessions via document_ids.
    """

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    file_type: Mapped[str] = mapped_column(String(16))          # "pdf" | "text"
    raw_text: Mapped[str] = mapped_column(Text)                 # full extracted content
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # Sessions that referenced this document
    sessions: Mapped[list["SessionRecord"]] = relationship(
        "SessionRecord",
        secondary="session_documents",
        back_populates="documents",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Session ↔ Document association (many-to-many)
# ─────────────────────────────────────────────────────────────────────────────

session_documents = Table(
    "session_documents",
    Base.metadata,
    Column("session_id", String(36), ForeignKey("session_records.id"), primary_key=True),
    Column("document_id", String(36), ForeignKey("documents.id"), primary_key=True),
)


# ─────────────────────────────────────────────────────────────────────────────
# Session Record
# ─────────────────────────────────────────────────────────────────────────────

class SessionRecord(Base):
    """One row per student session created via POST /start."""

    __tablename__ = "session_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    status: Mapped[str] = mapped_column(String(32), default="quiz_pending")
    # "quiz_pending" → "plan_generated"

    # PanicState fields
    panic_level: Mapped[int] = mapped_column(Integer, default=5)
    topics_mentioned: Mapped[str] = mapped_column(Text, default="[]")   # JSON list
    time_available_hours: Mapped[float] = mapped_column(Float, default=4.0)
    urgency_reason: Mapped[str] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    extracted_text: Mapped[str] = mapped_column(Text, default="")       # raw input
    notes_text: Mapped[str] = mapped_column(Text, default="")           # extracted from file

    # Relationships
    questions: Mapped[list["QuizQuestionRecord"]] = relationship(
        "QuizQuestionRecord", back_populates="session", cascade="all, delete-orphan"
    )
    submissions: Mapped[list["QuizSubmissionRecord"]] = relationship(
        "QuizSubmissionRecord", back_populates="session", cascade="all, delete-orphan"
    )
    study_plan: Mapped["StudyPlanRecord | None"] = relationship(
        "StudyPlanRecord", back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    documents: Mapped[list["DocumentRecord"]] = relationship(
        "DocumentRecord",
        secondary="session_documents",
        back_populates="sessions",
    )

    # Helpers
    def get_topics(self) -> list[str]:
        return json.loads(self.topics_mentioned)

    def set_topics(self, topics: list[str]) -> None:
        self.topics_mentioned = json.dumps(topics)


# ─────────────────────────────────────────────────────────────────────────────
# Quiz Questions
# ─────────────────────────────────────────────────────────────────────────────

class QuizQuestionRecord(Base):
    """MCQ question generated for a session."""

    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("session_records.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(8))     # "q1", "q2", …
    topic: Mapped[str] = mapped_column(String(255))
    question: Mapped[str] = mapped_column(Text)
    choices: Mapped[str] = mapped_column(Text)               # JSON list of 4 choices
    correct_answer: Mapped[str] = mapped_column(String(1))   # "A"|"B"|"C"|"D"
    difficulty: Mapped[str] = mapped_column(String(16), default="medium")

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="questions")

    def get_choices(self) -> list[str]:
        return json.loads(self.choices)

    def set_choices(self, choices: list[str]) -> None:
        self.choices = json.dumps(choices)


# ─────────────────────────────────────────────────────────────────────────────
# Quiz Submissions (student answers)
# ─────────────────────────────────────────────────────────────────────────────

class QuizSubmissionRecord(Base):
    """One row per answer the student submitted."""

    __tablename__ = "quiz_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("session_records.id"), index=True)
    question_id: Mapped[str] = mapped_column(String(8))      # "q1", "q2", …
    topic: Mapped[str] = mapped_column(String(255))
    selected_answer: Mapped[str] = mapped_column(String(1))  # "A"|"B"|"C"|"D"
    correct_answer: Mapped[str] = mapped_column(String(1))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="submissions")


# ─────────────────────────────────────────────────────────────────────────────
# Study Plan
# ─────────────────────────────────────────────────────────────────────────────

class StudyPlanRecord(Base):
    """Adaptive study plan generated after quiz scoring."""

    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("session_records.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    overall_score: Mapped[float] = mapped_column(Float, default=0.0)
    weak_topics: Mapped[str] = mapped_column(Text, default="[]")    # JSON list
    strong_topics: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    total_study_mins: Mapped[int] = mapped_column(Integer, default=0)
    motivational_note: Mapped[str] = mapped_column(Text, default="")

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="study_plan")
    sprints: Mapped[list["SprintSessionRecord"]] = relationship(
        "SprintSessionRecord", back_populates="study_plan", cascade="all, delete-orphan",
        order_by="SprintSessionRecord.sprint_number"
    )

    def get_weak_topics(self) -> list[str]:
        return json.loads(self.weak_topics)

    def set_weak_topics(self, topics: list[str]) -> None:
        self.weak_topics = json.dumps(topics)

    def get_strong_topics(self) -> list[str]:
        return json.loads(self.strong_topics)

    def set_strong_topics(self, topics: list[str]) -> None:
        self.strong_topics = json.dumps(topics)


# ─────────────────────────────────────────────────────────────────────────────
# Sprint Sessions
# ─────────────────────────────────────────────────────────────────────────────

class SprintSessionRecord(Base):
    """One sprint block within a study plan."""

    __tablename__ = "sprint_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study_plan_id: Mapped[int] = mapped_column(Integer, ForeignKey("study_plans.id"), index=True)
    sprint_number: Mapped[int] = mapped_column(Integer)
    topic: Mapped[str] = mapped_column(String(255))
    duration_mins: Mapped[int] = mapped_column(Integer)
    activity_type: Mapped[str] = mapped_column(String(64))
    questions: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of strings
    tips: Mapped[str] = mapped_column(Text, nullable=True)

    study_plan: Mapped["StudyPlanRecord"] = relationship("StudyPlanRecord", back_populates="sprints")

    def get_questions(self) -> list[str]:
        return json.loads(self.questions)

    def set_questions(self, qs: list[str]) -> None:
        self.questions = json.dumps(qs)
